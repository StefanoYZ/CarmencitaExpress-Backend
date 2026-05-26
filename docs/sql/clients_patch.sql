CREATE TABLE IF NOT EXISTS clientes (
    dni VARCHAR(8) PRIMARY KEY,
    nombre_completo VARCHAR(150) NOT NULL,
    telefono VARCHAR(9),
    correo VARCHAR(120),
    direccion VARCHAR(200),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

SELECT dni, nombre_completo, telefono, correo, direccion, created_at, updated_at
FROM clientes
ORDER BY updated_at DESC;
