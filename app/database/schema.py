from app.database.conexion_mysql import DB


SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS oficinas (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(255) NOT NULL UNIQUE,
        ciudad VARCHAR(255) NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB;
    """,
    """
    CREATE TABLE IF NOT EXISTS usuarios (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(255) NOT NULL,
        oficina_id INT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_usuario_oficina (nombre, oficina_id),
        CONSTRAINT fk_usuarios_oficina FOREIGN KEY (oficina_id)
            REFERENCES oficinas(id)
            ON DELETE SET NULL
    ) ENGINE=InnoDB;
    """,
    """
    CREATE TABLE IF NOT EXISTS impresoras (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(255) NOT NULL,
        numero_serie VARCHAR(180) NOT NULL UNIQUE,
        modelo VARCHAR(255) NULL,
        oficina_id INT NULL,
        ciudad VARCHAR(255) NULL,
        canal VARCHAR(60) NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_impresoras_oficina FOREIGN KEY (oficina_id)
            REFERENCES oficinas(id)
            ON DELETE SET NULL
    ) ENGINE=InnoDB;
    """,
    """
    CREATE TABLE IF NOT EXISTS impresiones (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        fecha DATE NOT NULL,
        usuario_id INT NULL,
        oficina_id INT NULL,
        impresora_id INT NULL,
        tipo_documento VARCHAR(100) NULL,
        paginas INT NOT NULL DEFAULT 0,
        contador_actual INT NULL,
        tipo_impresion ENUM('Color', 'BN') DEFAULT 'BN',
        file_hash CHAR(64) NOT NULL,
        row_hash CHAR(64) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_row_hash (row_hash),
        KEY idx_fecha (fecha),
        CONSTRAINT fk_impresiones_usuario FOREIGN KEY (usuario_id)
            REFERENCES usuarios(id)
            ON DELETE SET NULL,
        CONSTRAINT fk_impresiones_oficina FOREIGN KEY (oficina_id)
            REFERENCES oficinas(id)
            ON DELETE SET NULL,
        CONSTRAINT fk_impresiones_impresora FOREIGN KEY (impresora_id)
            REFERENCES impresoras(id)
            ON DELETE SET NULL
    ) ENGINE=InnoDB;
    """,
    """
    CREATE TABLE IF NOT EXISTS contadores (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        impresora_id INT NOT NULL,
        fecha DATE NOT NULL,
        contador_proveedor INT NOT NULL,
        contador_maquina INT NOT NULL,
        diferencia INT NOT NULL,
        porcentaje_error DECIMAL(8,4) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_contadores_impresora FOREIGN KEY (impresora_id)
            REFERENCES impresoras(id)
            ON DELETE CASCADE
    ) ENGINE=InnoDB;
    """,
    """
    CREATE TABLE IF NOT EXISTS mantenimientos (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        impresora_id INT NOT NULL,
        fecha_recomendacion DATE NOT NULL,
        paginas_acumuladas INT NOT NULL,
        tipo VARCHAR(60) NOT NULL,
        estado VARCHAR(60) NOT NULL DEFAULT 'Pendiente',
        descripcion VARCHAR(255) NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_mantenimientos_impresora FOREIGN KEY (impresora_id)
            REFERENCES impresoras(id)
            ON DELETE CASCADE
    ) ENGINE=InnoDB;
    """,
]

MIGRATION_SQL = [
    "ALTER TABLE oficinas MODIFY COLUMN nombre VARCHAR(255) NOT NULL",
    "ALTER TABLE oficinas MODIFY COLUMN ciudad VARCHAR(255) NULL",
    "ALTER TABLE usuarios MODIFY COLUMN nombre VARCHAR(255) NOT NULL",
    "ALTER TABLE impresoras MODIFY COLUMN nombre VARCHAR(255) NOT NULL",
    "ALTER TABLE impresoras MODIFY COLUMN numero_serie VARCHAR(180) NOT NULL",
    "ALTER TABLE impresoras MODIFY COLUMN modelo VARCHAR(255) NULL",
    "ALTER TABLE impresoras MODIFY COLUMN ciudad VARCHAR(255) NULL",
    "ALTER TABLE lecturas_email_impresoras ADD COLUMN IF NOT EXISTS message_uid VARCHAR(190) NULL",
    "ALTER TABLE lecturas_email_impresoras ADD COLUMN IF NOT EXISTS message_id VARCHAR(255) NULL",
    "ALTER TABLE lecturas_email_impresoras ADD COLUMN IF NOT EXISTS source_hash CHAR(64) NULL",
    "ALTER TABLE impresoras ADD COLUMN canal VARCHAR(60) NULL",
    "ALTER TABLE impresoras_red ADD COLUMN canal VARCHAR(60) NULL",
    "ALTER TABLE impresoras_red DROP INDEX uq_ip",
    "ALTER TABLE impresoras_red ADD INDEX idx_ip_address (ip_address)",
    "ALTER TABLE impresoras_red ADD COLUMN area VARCHAR(100) NULL",
    # Fix Bogota printers: assign correct canal / area, remove 'Administrativo'
    "UPDATE impresoras_red SET canal='INTERNO', area='TechOps'              WHERE numero_serie='R4P2805895'",
    "UPDATE impresoras_red SET canal='INTERNO', area=NULL                   WHERE numero_serie='1352800775'",
    "UPDATE impresoras_red SET canal='EXTERNO', area=NULL                   WHERE numero_serie='R4P0Y67374'",
    "UPDATE impresoras_red SET canal='EXTERNO', area='Oficina Comercial'    WHERE numero_serie='R4P8607199'",
    "UPDATE impresoras_red SET canal='INTERNO', area='CPL'                  WHERE numero_serie='R4P0Z68403'",
    "UPDATE impresoras_red SET canal='INTERNO', area='Soporte TI / Recepcion' WHERE numero_serie='R4P1172375'",
    "UPDATE impresoras_red SET canal='INTERNO', area='TMK'                  WHERE numero_serie='R4P1683592'",
    # Remove decommissioned printer KMA52A46 everywhere
    "DELETE FROM impresoras_red                WHERE numero_serie='KMA52A46'",
    "DELETE FROM lecturas_email_impresoras     WHERE serial_number='KMA52A46'",
    "DELETE FROM historial_lecturas_email      WHERE serial_number='KMA52A46'",
]

EXTRA_SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS reportes_comparativos (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        periodo CHAR(7) NOT NULL,
        numero_serie VARCHAR(180) NOT NULL,
        oficina VARCHAR(255) NULL,
        contador_proveedor INT NOT NULL,
        contador_maquina INT NOT NULL,
        diferencia INT NOT NULL,
        porcentaje_error DECIMAL(8,4) NOT NULL,
        fuente VARCHAR(60) DEFAULT 'manual',
        guardado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_rep_periodo_serie (periodo, numero_serie),
        INDEX idx_rep_periodo (periodo)
    ) ENGINE=InnoDB;
    """,
    """
    CREATE TABLE IF NOT EXISTS impresoras_red (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(255) NOT NULL,
        numero_serie VARCHAR(180) NULL,
        oficina VARCHAR(255) NULL,
        ip_address VARCHAR(45) NOT NULL,
        modelo VARCHAR(100) NULL DEFAULT 'M3655idn',
        canal VARCHAR(60) NULL,
        area VARCHAR(100) NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_ip (ip_address),
        INDEX idx_ir_serie (numero_serie)
    ) ENGINE=InnoDB;
    """,
    """
    CREATE TABLE IF NOT EXISTS lecturas_snmp (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        ip_address VARCHAR(45) NOT NULL,
        nombre VARCHAR(255) NULL,
        oficina VARCHAR(255) NULL,
        total_paginas INT NULL,
        kyocera_total INT NULL,
        mono INT NULL,
        color INT NULL,
        leido_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_snmp_ip (ip_address),
        INDEX idx_snmp_tiempo (leido_en)
    ) ENGINE=InnoDB;
    """,
    """
    CREATE TABLE IF NOT EXISTS lecturas_email_impresoras (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        message_uid VARCHAR(190) NULL,
        message_id VARCHAR(255) NULL,
        source_hash CHAR(64) NOT NULL,
        remitente VARCHAR(255) NULL,
        asunto VARCHAR(255) NULL,
        fecha_correo DATETIME NULL,
        serial_number VARCHAR(180) NULL,
        model_name VARCHAR(255) NULL,
        office_hint VARCHAR(255) NULL,
        meter_date DATETIME NULL,
        printed_total INT NULL,
        scanned_total INT NULL,
        duplex_1sided INT NULL,
        duplex_2sided INT NULL,
        duplex_total INT NULL,
        combine_total INT NULL,
        toner_black_pct INT NULL,
        contador_efectivo INT NULL,
        eventos_json LONGTEXT NULL,
        raw_body LONGTEXT NULL,
        imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_email_hash (source_hash),
        UNIQUE KEY uq_email_uid (message_uid),
        INDEX idx_email_serial (serial_number),
        INDEX idx_email_meter_date (meter_date),
        INDEX idx_email_imported (imported_at)
    ) ENGINE=InnoDB;
    """,
    """
    CREATE TABLE IF NOT EXISTS historial_lecturas_email (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        serial_number VARCHAR(180) NOT NULL,
        model_name VARCHAR(255) NULL,
        oficina VARCHAR(255) NULL,
        contador_efectivo INT NULL,
        printed_total INT NULL,
        scanned_total INT NULL,
        toner_black_pct INT NULL,
        meter_date DATETIME NULL,
        asunto VARCHAR(255) NULL,
        remitente VARCHAR(255) NULL,
        leido_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_hist_serial (serial_number),
        INDEX idx_hist_tiempo (leido_en),
        INDEX idx_hist_serial_tiempo (serial_number, leido_en DESC)
    ) ENGINE=InnoDB;
    """,
]


def initialize_database() -> None:
    for statement in SCHEMA_SQL:
        DB.execute(statement)

    # Best-effort schema widening for already-created databases.
    for statement in MIGRATION_SQL:
        try:
            DB.execute(statement)
        except Exception:
            # Ignore migration errors so startup is resilient across environments.
            pass

    for statement in EXTRA_SCHEMA_SQL:
        DB.execute(statement)
