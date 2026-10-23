-- ResiliMES factory seed for the Zetaris SQL editor.
-- Generated from data/sample. Do not edit by hand; run: python scripts/export_zetaris_sql.py
--
-- Assumption: the organisation can create tables in a database named
-- `resilimes`. If the SQL editor rejects CREATE TABLE, register the CSVs in
-- data/zetaris/ as Lightning tables with the same names and set ZETARIS_SCHEMA.
-- Numeric columns are VARCHAR on purpose. The application casts them.

CREATE TABLE resilimes.equipment (equipment_id VARCHAR(256), name VARCHAR(256), area VARCHAR(256), status VARCHAR(256), capability VARCHAR(256), setup_time_min VARCHAR(256), operators_required VARCHAR(256), max_wip VARCHAR(256), mtbf_hours VARCHAR(256), last_pm_at VARCHAR(256), fault_code VARCHAR(256), down_since VARCHAR(256));
INSERT INTO resilimes.equipment (equipment_id, name, area, status, capability, setup_time_min, operators_required, max_wip, mtbf_hours, last_pm_at, fault_code, down_since) VALUES ('LITHO-01', 'Lithography Scanner 01', 'Lithography', 'RUNNING', 'litho_193nm', '45', '1', '2', '120', '2026-10-18T08:00:00Z', NULL, NULL);
INSERT INTO resilimes.equipment (equipment_id, name, area, status, capability, setup_time_min, operators_required, max_wip, mtbf_hours, last_pm_at, fault_code, down_since) VALUES ('LITHO-02', 'Lithography Scanner 02', 'Lithography', 'DOWN', 'litho_193nm', '45', '1', '2', '110', '2026-10-10T08:00:00Z', 'LASER_FAULT', '2026-10-22T06:12:00Z');
INSERT INTO resilimes.equipment (equipment_id, name, area, status, capability, setup_time_min, operators_required, max_wip, mtbf_hours, last_pm_at, fault_code, down_since) VALUES ('ETCH-01', 'Plasma Etcher 01', 'Etch', 'RUNNING', 'etch_dielectric', '30', '1', '3', '200', '2026-10-20T06:00:00Z', NULL, NULL);
INSERT INTO resilimes.equipment (equipment_id, name, area, status, capability, setup_time_min, operators_required, max_wip, mtbf_hours, last_pm_at, fault_code, down_since) VALUES ('ETCH-02', 'Plasma Etcher 02', 'Etch', 'IDLE', 'etch_dielectric,etch_metal', '35', '1', '3', '180', '2026-10-19T14:00:00Z', NULL, NULL);
INSERT INTO resilimes.equipment (equipment_id, name, area, status, capability, setup_time_min, operators_required, max_wip, mtbf_hours, last_pm_at, fault_code, down_since) VALUES ('CMP-01', 'CMP Polisher 01', 'CMP', 'RUNNING', 'cmp_oxide', '20', '1', '4', '160', '2026-10-21T02:00:00Z', NULL, NULL);
INSERT INTO resilimes.equipment (equipment_id, name, area, status, capability, setup_time_min, operators_required, max_wip, mtbf_hours, last_pm_at, fault_code, down_since) VALUES ('DEP-01', 'CVD Deposition 01', 'Deposition', 'MAINTENANCE', 'cvd_oxide', '40', '2', '2', '150', '2026-10-22T04:00:00Z', NULL, NULL);

CREATE TABLE resilimes.wip_jobs (job_id VARCHAR(256), product_id VARCHAR(256), priority VARCHAR(256), qty VARCHAR(256), current_step VARCHAR(256), assigned_equipment VARCHAR(256), status VARCHAR(256), due_at VARCHAR(256), started_at VARCHAR(256), process_time_min VARCHAR(256), remaining_steps VARCHAR(256), preferred_equipment VARCHAR(256));
INSERT INTO resilimes.wip_jobs (job_id, product_id, priority, qty, current_step, assigned_equipment, status, due_at, started_at, process_time_min, remaining_steps, preferred_equipment) VALUES ('LOT-1001', 'PROD-A28', '1', '25', 'LITHO', 'LITHO-02', 'BLOCKED', '2026-10-22T18:00:00Z', '2026-10-22T05:40:00Z', '90', 'ETCH,CMP', NULL);
INSERT INTO resilimes.wip_jobs (job_id, product_id, priority, qty, current_step, assigned_equipment, status, due_at, started_at, process_time_min, remaining_steps, preferred_equipment) VALUES ('LOT-1002', 'PROD-A28', '2', '25', 'LITHO', 'LITHO-01', 'RUNNING', '2026-10-23T02:00:00Z', '2026-10-22T05:55:00Z', '90', 'ETCH,CMP', NULL);
INSERT INTO resilimes.wip_jobs (job_id, product_id, priority, qty, current_step, assigned_equipment, status, due_at, started_at, process_time_min, remaining_steps, preferred_equipment) VALUES ('LOT-1003', 'PROD-B14', '3', '50', 'ETCH', 'ETCH-01', 'RUNNING', '2026-10-23T12:00:00Z', '2026-10-22T04:10:00Z', '60', 'CMP', NULL);
INSERT INTO resilimes.wip_jobs (job_id, product_id, priority, qty, current_step, assigned_equipment, status, due_at, started_at, process_time_min, remaining_steps, preferred_equipment) VALUES ('LOT-1004', 'PROD-A28', '2', '25', 'QUEUED', NULL, 'QUEUED', '2026-10-23T08:00:00Z', NULL, '90', 'LITHO,ETCH,CMP', 'LITHO-01,LITHO-02');
INSERT INTO resilimes.wip_jobs (job_id, product_id, priority, qty, current_step, assigned_equipment, status, due_at, started_at, process_time_min, remaining_steps, preferred_equipment) VALUES ('LOT-1005', 'PROD-C07', '4', '12', 'CMP', 'CMP-01', 'RUNNING', '2026-10-22T22:00:00Z', '2026-10-22T06:00:00Z', '45', NULL, NULL);
INSERT INTO resilimes.wip_jobs (job_id, product_id, priority, qty, current_step, assigned_equipment, status, due_at, started_at, process_time_min, remaining_steps, preferred_equipment) VALUES ('LOT-1006', 'PROD-B14', '3', '50', 'QUEUED', NULL, 'QUEUED', '2026-10-24T00:00:00Z', NULL, '60', 'ETCH,CMP', 'ETCH-01,ETCH-02');

CREATE TABLE resilimes.products (product_id VARCHAR(256), name VARCHAR(256));
INSERT INTO resilimes.products (product_id, name) VALUES ('PROD-A28', 'Logic Node A28');
INSERT INTO resilimes.products (product_id, name) VALUES ('PROD-B14', 'Analog Node B14');
INSERT INTO resilimes.products (product_id, name) VALUES ('PROD-C07', 'Sensor Node C07');

CREATE TABLE resilimes.route_steps (product_id VARCHAR(256), step_index VARCHAR(256), step VARCHAR(256), capability VARCHAR(256), process_time_min VARCHAR(256), setup_family VARCHAR(256));
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family) VALUES ('PROD-A28', '0', 'LITHO', 'litho_193nm', '90', 'LITHO_A');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family) VALUES ('PROD-A28', '1', 'ETCH', 'etch_dielectric', '60', 'ETCH_D');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family) VALUES ('PROD-A28', '2', 'CMP', 'cmp_oxide', '45', 'CMP_OX');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family) VALUES ('PROD-B14', '0', 'ETCH', 'etch_metal', '60', 'ETCH_M');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family) VALUES ('PROD-B14', '1', 'CMP', 'cmp_oxide', '40', 'CMP_OX');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family) VALUES ('PROD-C07', '0', 'CMP', 'cmp_oxide', '45', 'CMP_OX');

CREATE TABLE resilimes.bom (product_id VARCHAR(256), material_id VARCHAR(256), qty_per_lot VARCHAR(256));
INSERT INTO resilimes.bom (product_id, material_id, qty_per_lot) VALUES ('PROD-A28', 'WAFER-300', '25');
INSERT INTO resilimes.bom (product_id, material_id, qty_per_lot) VALUES ('PROD-A28', 'RESIST-UV', '1');
INSERT INTO resilimes.bom (product_id, material_id, qty_per_lot) VALUES ('PROD-B14', 'WAFER-300', '50');
INSERT INTO resilimes.bom (product_id, material_id, qty_per_lot) VALUES ('PROD-B14', 'GAS-CF4', '2');
INSERT INTO resilimes.bom (product_id, material_id, qty_per_lot) VALUES ('PROD-C07', 'WAFER-200', '12');
INSERT INTO resilimes.bom (product_id, material_id, qty_per_lot) VALUES ('PROD-C07', 'SLURRY-OX', '1');

CREATE TABLE resilimes.materials (material_id VARCHAR(256), name VARCHAR(256), on_hand VARCHAR(256), unit VARCHAR(256));
INSERT INTO resilimes.materials (material_id, name, on_hand, unit) VALUES ('WAFER-300', '300mm prime wafer', '400', 'wafer');
INSERT INTO resilimes.materials (material_id, name, on_hand, unit) VALUES ('WAFER-200', '200mm prime wafer', '80', 'wafer');
INSERT INTO resilimes.materials (material_id, name, on_hand, unit) VALUES ('RESIST-UV', '193nm photoresist', '3', 'bottle');
INSERT INTO resilimes.materials (material_id, name, on_hand, unit) VALUES ('GAS-CF4', 'CF4 etch gas', '20', 'cylinder');
INSERT INTO resilimes.materials (material_id, name, on_hand, unit) VALUES ('SLURRY-OX', 'Oxide CMP slurry', '15', 'drum');

CREATE TABLE resilimes.operators (operator_id VARCHAR(256), name VARCHAR(256), certified VARCHAR(256), shift VARCHAR(256));
INSERT INTO resilimes.operators (operator_id, name, certified, shift) VALUES ('OP-01', 'A. Kim', 'litho_193nm,etch_dielectric', 'A');
INSERT INTO resilimes.operators (operator_id, name, certified, shift) VALUES ('OP-02', 'L. Nguyen', 'litho_193nm,cvd_oxide', 'A');
INSERT INTO resilimes.operators (operator_id, name, certified, shift) VALUES ('OP-03', 'M. Park', 'etch_dielectric,etch_metal,cmp_oxide', 'A');
INSERT INTO resilimes.operators (operator_id, name, certified, shift) VALUES ('OP-04', 'R. Singh', 'cmp_oxide,etch_metal', 'A');

CREATE TABLE resilimes.maintenance_logs (log_id VARCHAR(256), equipment_id VARCHAR(256), event_type VARCHAR(256), occurred_at VARCHAR(256), severity_code VARCHAR(256), description VARCHAR(256), estimated_repair_min VARCHAR(256), technician VARCHAR(256));
INSERT INTO resilimes.maintenance_logs (log_id, equipment_id, event_type, occurred_at, severity_code, description, estimated_repair_min, technician) VALUES ('M-9001', 'LITHO-02', 'FAULT', '2026-10-22T06:12:00Z', 'LASER_FAULT', 'Machine Litho-02 Down — laser source interlock tripped', '180', 'tech.kim');
INSERT INTO resilimes.maintenance_logs (log_id, equipment_id, event_type, occurred_at, severity_code, description, estimated_repair_min, technician) VALUES ('M-9002', 'LITHO-02', 'ALARM', '2026-10-22T06:05:00Z', 'TEMP_WARN', 'Scanner chamber temperature drift +2.1C before fault', '0', 'system');
INSERT INTO resilimes.maintenance_logs (log_id, equipment_id, event_type, occurred_at, severity_code, description, estimated_repair_min, technician) VALUES ('M-9003', 'DEP-01', 'PM_START', '2026-10-22T04:00:00Z', 'PM_CVD', 'Scheduled preventive maintenance window', '240', 'tech.nguyen');
INSERT INTO resilimes.maintenance_logs (log_id, equipment_id, event_type, occurred_at, severity_code, description, estimated_repair_min, technician) VALUES ('M-9004', 'ETCH-01', 'ALARM', '2026-10-21T22:14:00Z', 'RF_REFLECT', 'Transient RF reflection spike; auto-recovered', '0', 'system');
INSERT INTO resilimes.maintenance_logs (log_id, equipment_id, event_type, occurred_at, severity_code, description, estimated_repair_min, technician) VALUES ('M-9005', 'LITHO-01', 'PM_COMPLETE', '2026-10-18T08:00:00Z', 'PM_LITHO', 'Quarterly optics clean and calibration', '0', 'tech.park');
INSERT INTO resilimes.maintenance_logs (log_id, equipment_id, event_type, occurred_at, severity_code, description, estimated_repair_min, technician) VALUES ('M-9006', 'CMP-01', 'ALARM', '2026-10-21T11:02:00Z', 'PAD_WEAR', 'Pad wear near threshold; continue with monitoring', '0', 'system');
INSERT INTO resilimes.maintenance_logs (log_id, equipment_id, event_type, occurred_at, severity_code, description, estimated_repair_min, technician) VALUES ('M-9007', 'ETCH-02', 'FAULT', '2026-10-15T09:40:00Z', 'PUMP_DOWN', 'Roughing pump failure — repaired and returned to IDLE', '360', 'tech.kim');
INSERT INTO resilimes.maintenance_logs (log_id, equipment_id, event_type, occurred_at, severity_code, description, estimated_repair_min, technician) VALUES ('M-9008', 'LITHO-02', 'FAULT', '2026-10-10T16:20:00Z', 'STAGE_STALL', 'Wafer stage stall; parts replaced', '420', 'tech.nguyen');
