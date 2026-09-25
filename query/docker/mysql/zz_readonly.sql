CREATE USER IF NOT EXISTS 'shopkeeper_reader'@'%' IDENTIFIED BY 'local-reader-only';
GRANT SELECT ON dw.* TO 'shopkeeper_reader'@'%';
