# bgremove/views.py
import os
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from rembg import remove, new_session
from PIL import Image, ImageOps, ImageFilter, ImageEnhance
import io
import requests
from pathlib import Path
import base64
import time
import json

# Ruta del modelo
MODEL_DIR = Path.home() / ".u2net"
MODEL_PATH = MODEL_DIR / "u2netp.onnx"
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx"

# Sesiones de modelos disponibles
rembg_sessions = {
    'u2netp': None,
    'u2net': None,
    'silueta': None
}

def load_model():
    global rembg_sessions

    # Crear carpeta si no existe
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    # Descargar modelo si no está presente
    if not MODEL_PATH.exists():
        print("Descargando modelo U2Netp...")
        resp = requests.get(MODEL_URL, stream=True)
        resp.raise_for_status()
        with open(MODEL_PATH, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        print("Modelo U2Netp descargado correctamente.")

    # Cargar el modelo principal en memoria
    rembg_sessions['u2netp'] = new_session("u2netp")
    print("Modelo U2Netp cargado en memoria.")

def get_or_create_session(model_name):
    """Obtiene o crea una sesión del modelo especificado"""
    global rembg_sessions
    
    # Mapear nombres amigables a nombres técnicos
    model_mapping = {
        'u2netp': 'u2netp',  # CroPix Lite
        'u2net': 'u2net',    # CroPix Full
        'silueta': 'u2netp'  # Usa u2netp pero con procesamiento simplificado
    }
    
    # Obtener el nombre técnico del modelo
    technical_name = model_mapping.get(model_name, 'u2netp')
    
    if technical_name not in rembg_sessions:
        technical_name = 'u2netp'  # fallback
    
    if rembg_sessions[technical_name] is None:
        try:
            rembg_sessions[technical_name] = new_session(technical_name)
        except Exception as e:
            print(f"Error creando sesión {technical_name}: {e}")
            # Fallback a u2netp
            if rembg_sessions['u2netp'] is None:
                rembg_sessions['u2netp'] = new_session("u2netp")
            return rembg_sessions['u2netp']
    
    return rembg_sessions[technical_name]

def apply_edge_processing(img, mask, settings):
    """Aplica procesamiento de bordes según la configuración"""
    import numpy as np
    import cv2
    
    mask_np = np.array(mask)
    
    # Suavizado de bordes
    if settings.get('smooth_edges', True):
        edge_radius = settings.get('edge_radius', 5)
        mask_np = cv2.GaussianBlur(mask_np, (edge_radius*2+1, edge_radius*2+1), sigmaX=edge_radius/2)
    
    # Difuminado de bordes
    if settings.get('feather_edges', False):
        edge_radius = settings.get('edge_radius', 5)
        # Crear máscara de bordes
        edges = cv2.Canny(mask_np, 50, 150)
        
        # Dilatar los bordes
        kernel = np.ones((edge_radius, edge_radius), np.uint8)
        edges_dilated = cv2.dilate(edges, kernel, iterations=1)
        
        # Aplicar difuminado solo en los bordes
        mask_blurred = cv2.GaussianBlur(mask_np, (edge_radius*4+1, edge_radius*4+1), sigmaX=edge_radius)
        mask_np = np.where(edges_dilated > 0, mask_blurred, mask_np)
    
    return Image.fromarray(mask_np)

# Extraemos la lógica en una función reutilizable
def _process_image(img: Image.Image, mode: str, mask_data: str | None, settings: dict = None):
    import numpy as np, cv2, base64, io
    
    if settings is None:
        settings = {}
    
    # Obtener configuraciones
    ai_model = settings.get('ai_model', 'u2netp')
    quality = settings.get('quality', 'balanced')
    
    # Obtener sesión del modelo
    session = get_or_create_session(ai_model)
    
    # Ajustar calidad de procesamiento
    if quality == 'fast':
        # Redimensionar para procesamiento rápido
        original_size = img.size
        if max(img.size) > 512:
            img.thumbnail((512, 512), Image.Resampling.LANCZOS)
    elif quality == 'high':
        # Asegurar alta resolución
        if max(img.size) < 1024:
            scale_factor = 1024 / max(img.size)
            new_size = (int(img.width * scale_factor), int(img.height * scale_factor))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
    
    # Procesar con máscara del usuario si existe
    if mask_data:
        if "," in mask_data:
            _, b64 = mask_data.split(",", 1)
        else:
            b64 = mask_data
        mask_bytes = base64.b64decode(b64)
        user_mask = Image.open(io.BytesIO(mask_bytes)).convert("RGB")
        if user_mask.size != img.size:
            user_mask = user_mask.resize(img.size, Image.NEAREST)

        # IA: fondo automático
        if ai_model == 'silueta':
            # Para silueta, crear una máscara simple basada en contraste
            auto_result = img.convert('L')
            threshold = 128
            auto_mask = auto_result.point(lambda x: 255 if x > threshold else 0, mode='1')
            auto_mask = auto_mask.convert('L')
        else:
            auto_result = remove(img, session=session)
            auto_mask = auto_result.split()[-1]  # canal alpha

        user_mask_np = np.array(user_mask)
        auto_mask_np = np.array(auto_mask)

        # --- Tolerancia en color ---
        def is_near(c, t, tol=20):
            return np.all(np.abs(c - t) < tol, axis=-1)

        keep = is_near(user_mask_np, np.array([34,197,94]), 20)
        remove_ = is_near(user_mask_np, np.array([239,68,68]), 20)

        # --- Crea máscara binaria ---
        mask_bin = np.zeros_like(auto_mask_np)
        mask_bin[keep] = 255
        mask_bin[remove_] = 0
        untouched = ~(keep | remove_)
        mask_bin[untouched] = auto_mask_np[untouched]

        # Aplicar procesamiento de bordes
        mask_pil = Image.fromarray(np.clip(mask_bin, 0, 255).astype("uint8"))
        mask_processed = apply_edge_processing(img, mask_pil, settings)
        
        result = img.convert("RGBA")
        result.putalpha(mask_processed)
        
        # Restaurar tamaño original si se cambió para calidad rápida
        if quality == 'fast' and 'original_size' in locals():
            result = result.resize(original_size, Image.Resampling.LANCZOS)
        
        return result

    # Si no hay máscara, IA automática
    if ai_model == 'silueta':
        # Procesamiento de silueta simple
        gray = img.convert('L')
        
        # Mejorar contraste
        enhancer = ImageEnhance.Contrast(gray)
        gray = enhancer.enhance(1.5)
        
        # Aplicar threshold adaptivo
        import numpy as np
        gray_np = np.array(gray)
        threshold = np.mean(gray_np)
        mask = gray_np > threshold
        
        result = img.convert("RGBA")
        alpha = np.where(mask, 255, 0).astype(np.uint8)
        result.putalpha(Image.fromarray(alpha))
    else:
        result = remove(img, session=session)
        if result.mode != "RGBA":
            result = result.convert("RGBA")
    
    # Aplicar procesamiento de bordes si no es silueta
    if ai_model != 'silueta' and settings:
        alpha_channel = result.split()[-1]
        processed_alpha = apply_edge_processing(img, alpha_channel, settings)
        result.putalpha(processed_alpha)
    
    # Restaurar tamaño original si se cambió para calidad rápida
    if quality == 'fast' and 'original_size' in locals():
        result = result.resize(original_size, Image.Resampling.LANCZOS)
    
    return result

def api_remove_background(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Método no permitido"}, status=405)

    if "image" not in request.FILES:
        return JsonResponse({"success": False, "error": "Falta archivo 'image'"}, status=400)

    mode = request.POST.get("mode", "keep_subject")
    mask_data = request.POST.get("mask_data", "").strip()
    
    # Extraer configuraciones del frontend
    settings = {
        'ai_model': request.POST.get('ai_model', 'u2netp'),
        'quality': request.POST.get('quality', 'balanced'),
        'smooth_edges': request.POST.get('smooth_edges', 'true').lower() == 'true',
        'feather_edges': request.POST.get('feather_edges', 'false').lower() == 'true',
        'edge_radius': int(request.POST.get('edge_radius', '5')),
    }
    
    start_time = time.time()
    
    try:
        img = Image.open(request.FILES["image"]).convert("RGBA")
    except Exception as e:
        return JsonResponse({"success": False, "error": f"Imagen inválida: {str(e)}"}, status=400)

    try:
        # Validar límites de imagen - más restrictivos para móviles
        max_size = 3072  # Reducido de 4096
        min_size = 8     # Reducido de 10
        
        if img.width > max_size or img.height > max_size:
            return JsonResponse({"success": False, "error": f"Imagen demasiado grande (máximo {max_size}x{max_size})"}, status=400)
        
        if img.width < min_size or img.height < min_size:
            return JsonResponse({"success": False, "error": f"Imagen demasiado pequeña (mínimo {min_size}x{min_size})"}, status=400)
        
        # Optimización automática para imágenes grandes en calidad rápida
        if settings['quality'] == 'fast' and max(img.width, img.height) > 1024:
            scale_factor = 1024 / max(img.width, img.height)
            new_size = (int(img.width * scale_factor), int(img.height * scale_factor))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        result = _process_image(img, mode, mask_data, settings)
        
        # Optimizar formato de salida según configuración
        buf = io.BytesIO()
        
        # Si es de alta calidad, usar PNG con mejor compresión
        if settings['quality'] == 'high':
            result.save(buf, format="PNG", optimize=True, compress_level=6)
        else:
            result.save(buf, format="PNG", optimize=True, compress_level=1)
        
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode("ascii")
        
        processing_time = time.time() - start_time
        
        return JsonResponse({
            "success": True,
            "mode": mode,
            "image_data": f"data:image/png;base64,{b64}",
            "processing_time": round(processing_time * 1000),  # en milisegundos
            "settings_used": settings,
            "original_size": {"width": img.width, "height": img.height},
            "result_size": {"width": result.width, "height": result.height}
        })
        
    except Exception as e:
        error_msg = str(e)
        
        # Errores específicos más amigables
        if "out of memory" in error_msg.lower() or "memory" in error_msg.lower():
            error_msg = "Imagen demasiado grande para procesar. Intenta con una imagen más pequeña."
        elif "model" in error_msg.lower():
            error_msg = f"Error con el modelo {settings['ai_model']}. Intenta con otro modelo."
        elif "timeout" in error_msg.lower():
            error_msg = "El procesamiento tomó demasiado tiempo. Intenta con calidad 'rápida'."
        
        return JsonResponse({
            "success": False, 
            "error": error_msg,
            "processing_time": round((time.time() - start_time) * 1000)
        }, status=500)

# Cargamos el modelo al iniciar
load_model()

def remove_background(request):
    # Página HTML (frontend)
    if request.method == "GET":
        return render(request, "upload.html")
    # Si se hace POST normal (no JS), devolvemos binario legacy
    if request.method == "POST" and request.FILES.get("image"):
        mode = request.POST.get("mode", "keep_subject")
        mask_data = request.POST.get("mask_data", "").strip()
        img = Image.open(request.FILES["image"]).convert("RGBA")
        result = _process_image(img, mode, mask_data)
        buf = io.BytesIO()
        result.save(buf, format="PNG")
        buf.seek(0)
        return HttpResponse(buf, content_type="image/png")
    return HttpResponse(status=400)

def index(request):
    return render(request, "index.html")

def privacy(request):
    return render(request, "privacy.html")

def terms(request):
    return render(request, "terms.html")