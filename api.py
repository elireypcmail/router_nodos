"""
Punto de entrada legacy — redirige a main.py (FastAPI).

El servidor TCP en :8888 fue reemplazado por la API HTTPS en main.py.
"""

from main import run

if __name__ == "__main__":
    run()
