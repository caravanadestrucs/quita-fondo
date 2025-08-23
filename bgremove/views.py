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
rembg_session = None

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
    """
    Devuelve un objeto PIL (resultado) según el modo.
    Si mask_data contiene una máscara guiada, intenta usar GrabCut.
    """
    # Normalizamos modo
    if mode not in ("keep_subject", "keep_background", "mask"):
        mode = "keep_subject"

    # Intento con máscara guiada (GrabCut)
    if mask_data:
        try:
            import numpy as np, cv2, base64, io
            if "," in mask_data:
                _, b64 = mask_data.split(",", 1)
            else:
                b64 = mask_data
            mask_bytes = base64.b64decode(b64)
            user_mask = Image.open(io.BytesIO(mask_bytes)).convert("L")
            if user_mask.size != img.size:
                user_mask = user_mask.resize(img.size, Image.NEAREST)

            rgb = img.convert("RGB")
            img_np = np.array(rgb)
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

            m = np.array(user_mask)
            gc_mask = np.full(m.shape, cv2.GC_PR_BGD, dtype=np.uint8)
            gc_mask[m <= 10] = cv2.GC_BGD
            gc_mask[m >= 245] = cv2.GC_FGD

            bgdModel = np.zeros((1, 65), np.float64)
            fgdModel = np.zeros((1, 65), np.float64)
            cv2.grabCut(img_bgr, gc_mask, None, bgdModel, fgdModel, 5, cv2.GC_INIT_WITH_MASK)

            final_mask_np = np.where(
                (gc_mask == cv2.GC_FGD) | (gc_mask == cv2.GC_PR_FGD), 255, 0
            ).astype("uint8")
            final_mask = Image.fromarray(final_mask_np, mode="L")

            if mode == "mask":
                return final_mask

            base = img.copy()
            if mode == "keep_subject":
                alpha = final_mask
            else:
                alpha = ImageOps.invert(final_mask)
            base.putalpha(alpha)
            return base
        except Exception:
            # Fallback automático
            pass

    # Flujo automático rembg
    if mode == "keep_subject":
        output_img = remove(img, session=rembg_session)
        if output_img.mode != "RGBA":
            output_img = output_img.convert("RGBA")
    elif mode == "keep_background":
        mask = remove(img, session=rembg_session, only_mask=True)
        if mask.mode != "L":
            mask = mask.convert("L")
        inv_mask = ImageOps.invert(mask)
        base = img.copy()
        base.putalpha(inv_mask)
        output_img = base
    else:  # mask
        mask = remove(img, session=rembg_session, only_mask=True)
        if mask.mode != "L":
            mask = mask.convert("L")
        output_img = mask
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