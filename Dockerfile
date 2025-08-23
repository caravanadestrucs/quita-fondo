FROM python:3.11-slim

# Instala dependencias del sistema
RUN apt-get update && apt-get install -y \
    build-essential \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Establece el directorio de trabajo
WORKDIR /app

# Copia los archivos del proyecto
COPY . /app

# Instala dependencias de Python
RUN pip install --upgrade pip
RUN pip install django rembg pillow gunicorn

# Expone el puerto de Django
EXPOSE 8000

# Comando para iniciar el servidor con Gunicorn
CMD ["gunicorn", "bgproject.wsgi:application", "--bind", "0.0.0.0:8000"]