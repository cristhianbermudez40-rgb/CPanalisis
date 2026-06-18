#!/usr/bin/env python3
"""
Script para cargar masivamente todas las impresoras registradas en el sistema.
Basado en la tabla de referencia del usuario.
"""

import sys
import os
from pathlib import Path

# Agregar ruta del proyecto - necesario para importar módulos
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.insert(0, str(project_root))
os.chdir(str(project_root))

from app.config import APP_CONFIG
from app.database.conexion_mysql import DB
from app.controllers.print_controller import PrintController

# Datos de las impresoras - tabla del usuario
IMPRESORAS_DATA = [
    # (nombre_modelo, numero_serie, ip_address, ciudad, canal/oficina)
    ("ECOSYS M3655idn INTERNO", "R4P1171228", "192.168.40.20", "Armenia", "INTERNO"),
    ("ECOSYS M3655idn", "R4P0Y673740", "192.168.1.53", "Barranquilla", "EXTERNO"),
    ("ECOSYS M3655idn", "R4P1682502", "192.168.20.30", "Barranquilla", "INTERNO"),
    ("ECOSYS M3655idn", "R4P2805895", "10.100.10.12", "Bogota", "Administrativo"),
    ("ECOSYS M3655idn/A", "1352800775", "10.100.10.30", "Bogota", "INTERNO"),
    ("ECOSYS M3655idn", "R4P0Y673742", "10.100.10.15", "Bogota", "EXTERNO"),
    ("ECOSYS M3655idn", "R4P8607199", "10.100.10.4", "Bogota", "EXTERNO"),
    ("ECOSYS M3655idn", "R4P0Z68403", "10.100.10.5", "Bogota", "Administrativo"),
    ("ECOSYS M3655idn", "R4P1172375", "10.100.10.25", "Bogota", "Administrativo"),
    ("ECOSYS M3655idn", "R4P1683592", "10.100.10.9", "Bogota", "Administrativo"),
    ("ECOSYS M3655idn", "R4P0Y67044", "192.168.0.14", "Bucaramanga", "EXTERNO"),
    ("ECOSYS M3655idn", "R4P0Y66966", "192.168.60.51", "Bucaramanga", "INTERNO"),
    ("ECOSYS M3655idn", "R4P0Y65436", "192.168.1.51", "Cali", "EXTERNO"),
    ("ECOSYS M3655idn", "R4P0Y66787", "192.168.66.51", "Cali", "INTERNO"),
    ("ECOSYS M3655idn", "R4P0Y67381", "192.168.1.20", "Cartagena", "EXTERNO"),
    ("ECOSYS M3655idn", "R4P0Y66790", "192.168.127.51", "Cartagena", "INTERNO"),
    ("ECOSYS M3655idn", "R4P0Y65427", "192.168.87.15", "Cucuta", "INTERNO"),
    ("ECOSYS M3655idn", "R4P0Z69074", "192.168.156.51", "Fusagasugá", "INTERNO"),
    ("ECOSYS M3655idn", "R4P0Y66708", "192.168.123.51", "Girardot", "INTERNO"),
    ("ECOSYS M3655idn", "R4P0Z67812", "192.168.1.100", "Ibague", "EXTERNO"),
    ("ECOSYS M3655idn", "R4P0Z67822", "192.168.100.250", "Ibague", "INTERNO"),
    ("ECOSYS M3655idn", "R4P0Y65438", "192.168.72.51", "Medellin", "INTERNO"),
    ("ECOSYS M3655idn", "R4P0Y66908", "192.168.71.50", "Medellin", "EXTERNO"),
    ("ECOSYS M3655idn", "R4P0Y66781", "192.168.129.51", "Monteria", "INTERNO"),
    ("ECOSYS M3655idn", "R4P0Y65507", "192.168.73.51", "Neiva", "INTERNO"),
    ("ECOSYS M3655idn", "R4P0Z67819", "192.168.85.51", "Pereira", "INTERNO"),
    ("ECOSYS M3655idn", "R4P0354322", "192.168.134.52", "Santa Marta", "INTERNO"),
    ("ECOSYS M3655idn", "R4P0Y66956", "192.168.86.16", "Sincelejo", "INTERNO"),
    ("ECOSYS M3655idn", "R4P0Z68453", "192.168.54.51", "Soacha", "INTERNO"),
    ("ECOSYS M3655idn", "R4P0Y66711", "192.168.89.51", "Soledad-Atl", "INTERNO"),
    ("ECOSYS M3655idn", "R4P0Y66797", "192.168.65.51", "Valledupar", "INTERNO"),
    ("ECOSYS M3655idn", "KM452A6", "192.168.0.20", "Cartagena", "EXTERNO"),
    
    # Impresoras sin IP (solo con serial en correo)
    ("ECOSYS M3655idn", "R4P0Y66663", None, "Neiva", "INTERNO"),  # Neiva sin IP
]

def main():
    print("=" * 60)
    print("LIMPIANDO impresoras existentes...")
    print("=" * 60)
    
    # Limpiar impresoras existentes para recargar correctamente
    try:
        DB.execute("DELETE FROM impresoras_red")
        DB.execute("DELETE FROM impresoras")
        print("✅ Base de datos limpiada")
    except Exception as e:
        print(f"⚠️ Error limpiando BD: {e}")
    
    print("\n" + "=" * 60)
    print("Cargando impresoras masivamente...")
    print("=" * 60)
    
    controller = PrintController()
    impresoras_para_cargar = []
    impresoras_sin_ip = []
    
    for nombre, serial, ip, ciudad, canal in IMPRESORAS_DATA:
        if ip:
            # Si tiene IP, cargarla en impresoras_red
            impresoras_para_cargar.append({
                "nombre": nombre,  # Mantener nombre original
                "numero_serie": serial,
                "ip_address": ip,
                "oficina": ciudad,  # La oficina ES la ciudad
                "modelo": "M3655idn",
            })
        else:
            # Sin IP, guardar para procesarla aparte en la tabla de inventario
            impresoras_sin_ip.append({
                "nombre": nombre,
                "numero_serie": serial,
                "ciudad": ciudad,
                "oficina": ciudad,  # La oficina ES la ciudad
                "modelo": "M3655idn",
            })
    
    # Cargar impresoras con IP
    if impresoras_para_cargar:
        resultado = controller.cargar_impresoras_lote(impresoras_para_cargar)
        print(f"\n✅ Carga por IP: {resultado['mensaje']}")
        if resultado.get('errores'):
            print("   Errores:")
            for error in resultado['errores']:
                print(f"   - {error}")
    
    # Cargar impresoras sin IP en la tabla de inventario
    if impresoras_sin_ip:
        print(f"\n📝 Registrando {len(impresoras_sin_ip)} impresora(s) sin IP en inventario:")
        for imp in impresoras_sin_ip:
            try:
                DB.execute(
                    """
                    INSERT INTO impresoras (nombre, numero_serie, modelo, ciudad)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        nombre = VALUES(nombre),
                        modelo = VALUES(modelo),
                        ciudad = VALUES(ciudad)
                    """,
                    (imp["nombre"], imp["numero_serie"], imp["modelo"], imp["ciudad"]),
                )
                print(f"   ✓ {imp['numero_serie']} - {imp['ciudad']}")
            except Exception as e:
                print(f"   ✗ {imp['numero_serie']}: {e}")
    
    print("\n" + "=" * 60)
    print("✅ Carga completada!")
    print("=" * 60)

if __name__ == "__main__":
    main()
