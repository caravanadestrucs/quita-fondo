# bgremove/views.py
import os
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from rembg import remove, new_session
from PIL import Image, ImageOps
import io
import requests
from pathlib import Path
import base64

# Ruta del modelo
MODEL_DIR = Path.home() / ".u2net"
MODEL_PATH = MODEL_DIR / "u2net.onnx"
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx"

# Inicializamos la sesión global
rembg_session = new_session("sam")

def load_model():
    global rembg_session

    # Crear carpeta si no existe
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    # Descargar modelo si no está presente
    if not MODEL_PATH.exists():
        print("Descargando modelo U2Net...")
        resp = requests.get(MODEL_URL, stream=True)
        resp.raise_for_status()
        with open(MODEL_PATH, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        print("Modelo descargado correctamente.")

    # Cargar el modelo en memoria
    rembg_session = new_session("u2net")

# Cargamos el modelo al iniciar
load_model()

# Extraemos la lógica en una función reutilizable
def _process_image(img: Image.Image, mode: str, mask_data: str | None):
    import numpy as np, cv2, base64, io
    # Usa SAM para el recorte automático
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
        auto_result = remove(img, session=rembg_session)
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

        # --- Filtro para mejorar bordes ---
        # Suaviza bordes con blur
        mask_bin = cv2.GaussianBlur(mask_bin, (11,11), sigmaX=5)
        # Detecta bordes y los refuerza
        edges = cv2.Canny(mask_bin, 50, 150)
        mask_bin[edges > 0] = 255  # Refuerza bordes detectados

        # Opcional: dilata para expandir zonas pintadas
        mask_bin = cv2.dilate(mask_bin, np.ones((5,5), np.uint8), iterations=1)

        mask_bin = np.clip(mask_bin, 0, 255).astype("uint8")
        result = img.convert("RGBA")
        result.putalpha(Image.fromarray(mask_bin))
        return result

    # Si no hay máscara, IA automática
    output_img = remove(img, session=rembg_session)
    if output_img.mode != "RGBA":
        output_img = output_img.convert("RGBA")
    return output_img

def api_remove_background(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Método no permitido"}, status=405)
    if "image" not in request.FILES:
        return JsonResponse({"success": False, "error": "Falta archivo 'image'"}, status=400)

    mode = request.POST.get("mode", "keep_subject")
    mask_data = request.POST.get("mask_data", "").strip()
    try:
        img = Image.open(request.FILES["image"]).convert("RGBA")
    except Exception:
        return JsonResponse({"success": False, "error": "Imagen inválida"}, status=400)

    try:
        result = _process_image(img, mode, mask_data)
        buf = io.BytesIO()
        # Si es máscara en L, guardamos PNG igualmente
        result.save(buf, format="PNG")
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode("ascii")
        return JsonResponse({
            "success": True,
            "mode": mode,
            "image_data": f"data:image/png;base64,{b64}"
        })
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)

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