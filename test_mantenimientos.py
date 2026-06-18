#!/usr/bin/env python
"""Script de prueba para validar sincronización de mantenimientos."""

from pathlib import Path
import sys

# Agregar proyecto al path
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.database.conexion_mysql import DB
from app.controllers.print_controller import PrintController


def test_mantenimientos():
    """Prueba la generación y sincronización de mantenimientos."""
    print("\n" + "=" * 80)
    print("PRUEBA: Mantenimientos - Generacion y Sincronizacion")
    print("=" * 80 + "\n")

    controller = PrintController()

    # 1. Obtener recomendaciones
    print("[PASO 1] Obteniendo recomendaciones de mantenimiento...")
    print("-" * 80)
    try:
        recommendations = controller.programa_mantenimiento()
        print(f"[OK] {len(recommendations)} recomendaciones generadas\n")

        for i, rec in enumerate(recommendations[:5]):
            print(f"  {i+1}. Serial: {rec.get('numero_serie'):<20} "
                  f"Oficina: {rec.get('oficina'):<15} "
                  f"Estado: {rec.get('estado'):<10} "
                  f"Prioridad: {rec.get('prioridad')}")
        if len(recommendations) > 5:
            print(f"  ... y {len(recommendations) - 5} mas")

    except Exception as exc:
        print(f"[ERROR] {exc}")
        return False

    # 2. Sincronizar mantenimientos
    print("\n[PASO 2] Sincronizando mantenimientos a BD...")
    print("-" * 80)
    try:
        result = controller.sincronizar_mantenimientos(regenerar=False)
        print(f"[OK] {result.get('mensaje')}")
        print(f"     Generados: {result.get('generados')}")
        print(f"     Existentes: {result.get('existentes')}")
        print(f"     Total: {result.get('total')}\n")
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return False

    # 3. Obtener mantenimientos vigentes
    print("[PASO 3] Obteniendo mantenimientos vigentes de BD...")
    print("-" * 80)
    try:
        mantenimientos = controller.obtener_mantenimientos_vigentes()
        print(f"[OK] {len(mantenimientos)} mantenimientos vigentes\n")

        for i, mant in enumerate(mantenimientos[:10]):
            print(f"  {i+1}. Serial: {mant.get('numero_serie'):<20} "
                  f"Tipo: {mant.get('tipo'):<25} "
                  f"Estado: {mant.get('estado'):<10} "
                  f"Paginas: {mant.get('paginas_acumuladas')}")
        if len(mantenimientos) > 10:
            print(f"  ... y {len(mantenimientos) - 10} mas")

    except Exception as exc:
        print(f"[ERROR] {exc}")
        return False

    # 4. Validar en BD directamente
    print("\n[PASO 4] Validacion en BD...")
    print("-" * 80)
    try:
        stats = DB.fetch_one(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN estado = 'VENCIDO' THEN 1 ELSE 0 END) as vencidos,
                SUM(CASE WHEN estado = 'PROXIMO' THEN 1 ELSE 0 END) as proximos,
                SUM(CASE WHEN estado = 'PROGRAMAR' THEN 1 ELSE 0 END) as programar,
                SUM(CASE WHEN estado = 'CONTROL' THEN 1 ELSE 0 END) as control
            FROM mantenimientos
            """
        )
        print(f"[OK] Estadisticas de mantenimientos:")
        print(f"     Total: {stats.get('total', 0)}")
        print(f"     Vencidos: {stats.get('vencidos', 0)}")
        print(f"     Proximos: {stats.get('proximos', 0)}")
        print(f"     Programar: {stats.get('programar', 0)}")
        print(f"     Control: {stats.get('control', 0)}\n")

    except Exception as exc:
        print(f"[ERROR] {exc}")
        return False

    print("=" * 80)
    print("[EXITO] PRUEBA DE MANTENIMIENTOS COMPLETADA")
    print("=" * 80 + "\n")
    return True


if __name__ == "__main__":
    success = test_mantenimientos()
    sys.exit(0 if success else 1)
