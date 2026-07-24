"""Captura pantallas del sistema para el manual."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "imagenes"
BASE = "http://127.0.0.1:8000"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    shots: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1360, "height": 860}, device_scale_factor=1.25)
        page = ctx.new_page()

        def shot(name: str, full: bool = False) -> None:
            path = OUT / name
            page.screenshot(path=str(path), full_page=full)
            shots.append(name)
            print("saved", name)

        page.goto(f"{BASE}/login/", wait_until="networkidle")
        page.wait_for_timeout(900)
        shot("01_login.png")

        page.goto(f"{BASE}/catalogo/", wait_until="networkidle")
        page.wait_for_timeout(900)
        shot("02_catalogo_publico.png", full=True)

        page.goto(f"{BASE}/login/", wait_until="networkidle")
        page.fill('input[name="username"]', "admin")
        page.fill('input[name="password"]', "Admin12345!")
        page.click('button[type="submit"]')
        page.wait_for_timeout(1800)
        shot("03_despues_login.png", full=True)

        routes = [
            ("/app/", "04_gestion_inicio.png"),
            ("/app/vendedores/", "05_vendedores.png"),
            ("/app/asesores-alquiler/", "06_asesores_alquiler.png"),
            ("/app/clientes/", "07_clientes.png"),
            ("/app/inmuebles/venta/", "08_inmuebles_venta.png"),
            ("/app/inmuebles/alquileres/", "09_inmuebles_alquiler.png"),
            ("/app/contratos/", "10_contratos.png"),
            ("/dashboard/", "11_dashboard.png"),
        ]
        for url, name in routes:
            try:
                resp = page.goto(f"{BASE}{url}", wait_until="networkidle", timeout=25000)
                page.wait_for_timeout(800)
                if resp and resp.status >= 400:
                    print("http", resp.status, name)
                shot(name, full=True)
            except Exception as exc:  # noqa: BLE001
                print("skip", name, exc)

        browser.close()
    print("TOTAL", len(shots))


if __name__ == "__main__":
    main()
