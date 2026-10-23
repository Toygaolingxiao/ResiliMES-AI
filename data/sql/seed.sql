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
INSERT INTO resilimes.equipment (equipment_id, name, area, status, capability, setup_time_min, operators_required, max_wip, mtbf_hours, last_pm_at, fault_code, down_since) VALUES ('DEP-01', 'CVD Deposition 01', 'Deposition', 'IDLE', 'cvd_oxide', '25', '1', '2', '150', '2026-10-22T04:00:00Z', NULL, NULL);
INSERT INTO resilimes.equipment (equipment_id, name, area, status, capability, setup_time_min, operators_required, max_wip, mtbf_hours, last_pm_at, fault_code, down_since) VALUES ('MEAS-01', 'Overlay and CD Metrology 01', 'Metrology', 'IDLE', 'overlay_cd', '12', '1', '2', '300', '2026-10-19T08:00:00Z', NULL, NULL);
INSERT INTO resilimes.equipment (equipment_id, name, area, status, capability, setup_time_min, operators_required, max_wip, mtbf_hours, last_pm_at, fault_code, down_since) VALUES ('WET-01', 'Wet Bench 01', 'Clean', 'IDLE', 'wet_clean', '10', '1', '4', '400', '2026-10-17T08:00:00Z', NULL, NULL);

CREATE TABLE resilimes.wip_jobs (job_id VARCHAR(256), product_id VARCHAR(256), priority VARCHAR(256), qty VARCHAR(256), current_step VARCHAR(256), assigned_equipment VARCHAR(256), status VARCHAR(256), due_at VARCHAR(256), started_at VARCHAR(256), process_time_min VARCHAR(256), remaining_steps VARCHAR(256), preferred_equipment VARCHAR(256), released_through VARCHAR(256), rework_of VARCHAR(256), rework_count VARCHAR(256), rework_limit VARCHAR(256), release_min VARCHAR(256));
INSERT INTO resilimes.wip_jobs (job_id, product_id, priority, qty, current_step, assigned_equipment, status, due_at, started_at, process_time_min, remaining_steps, preferred_equipment, released_through, rework_of, rework_count, rework_limit, release_min) VALUES ('LOT-1001', 'PROD-A28', '1', '25', 'LITHO', 'LITHO-02', 'BLOCKED', '2026-10-22T18:00:00Z', '2026-10-22T05:40:00Z', '75', 'MEAS,ETCH,CLEAN,CMP', NULL, 'CMP', NULL, '0', '1', '0');
INSERT INTO resilimes.wip_jobs (job_id, product_id, priority, qty, current_step, assigned_equipment, status, due_at, started_at, process_time_min, remaining_steps, preferred_equipment, released_through, rework_of, rework_count, rework_limit, release_min) VALUES ('LOT-1002', 'PROD-A28', '2', '25', 'LITHO', 'LITHO-01', 'RUNNING', '2026-10-23T02:00:00Z', '2026-10-22T06:25:00Z', '75', 'MEAS,ETCH,CLEAN,CMP', NULL, 'CMP', NULL, '0', '1', '0');
INSERT INTO resilimes.wip_jobs (job_id, product_id, priority, qty, current_step, assigned_equipment, status, due_at, started_at, process_time_min, remaining_steps, preferred_equipment, released_through, rework_of, rework_count, rework_limit, release_min) VALUES ('LOT-1003', 'PROD-B14', '3', '50', 'CLEAN', 'WET-01', 'RUNNING', '2026-10-23T12:00:00Z', '2026-10-22T06:00:00Z', '12', 'DEP-2', NULL, NULL, NULL, '0', '1', '0');
INSERT INTO resilimes.wip_jobs (job_id, product_id, priority, qty, current_step, assigned_equipment, status, due_at, started_at, process_time_min, remaining_steps, preferred_equipment, released_through, rework_of, rework_count, rework_limit, release_min) VALUES ('LOT-1004', 'PROD-A28', '2', '25', 'QUEUED', NULL, 'QUEUED', '2026-10-23T08:00:00Z', NULL, '28', 'DEP,LITHO,MEAS,ETCH,CLEAN,CMP', 'LITHO-01,LITHO-02', 'CMP', NULL, '0', '1', '0');
INSERT INTO resilimes.wip_jobs (job_id, product_id, priority, qty, current_step, assigned_equipment, status, due_at, started_at, process_time_min, remaining_steps, preferred_equipment, released_through, rework_of, rework_count, rework_limit, release_min) VALUES ('LOT-1005', 'PROD-C07', '4', '12', 'CMP', 'CMP-01', 'RUNNING', '2026-10-22T22:00:00Z', '2026-10-22T06:00:00Z', '45', NULL, NULL, NULL, NULL, '0', '1', '0');
INSERT INTO resilimes.wip_jobs (job_id, product_id, priority, qty, current_step, assigned_equipment, status, due_at, started_at, process_time_min, remaining_steps, preferred_equipment, released_through, rework_of, rework_count, rework_limit, release_min) VALUES ('LOT-1006', 'PROD-B14', '3', '50', 'QUEUED', NULL, 'QUEUED', '2026-10-24T00:00:00Z', NULL, '20', 'DEP,ETCH,CLEAN,DEP-2', 'ETCH-01,ETCH-02', NULL, NULL, '0', '1', '0');

CREATE TABLE resilimes.products (product_id VARCHAR(256), name VARCHAR(256), route_id VARCHAR(256));
INSERT INTO resilimes.products (product_id, name, route_id) VALUES ('PROD-A28', 'Logic Node A28', 'ROUTE-A28');
INSERT INTO resilimes.products (product_id, name, route_id) VALUES ('PROD-B14', 'Analog Node B14', 'ROUTE-B14');
INSERT INTO resilimes.products (product_id, name, route_id) VALUES ('PROD-C07', 'Sensor Node C07', 'ROUTE-C07');

CREATE TABLE resilimes.route (route_id VARCHAR(256), product_id VARCHAR(256), name VARCHAR(256));
INSERT INTO resilimes.route (route_id, product_id, name) VALUES ('ROUTE-A28', 'PROD-A28', 'Logic A28, two layers');
INSERT INTO resilimes.route (route_id, product_id, name) VALUES ('ROUTE-B14', 'PROD-B14', 'Analog B14 film cap');
INSERT INTO resilimes.route (route_id, product_id, name) VALUES ('ROUTE-C07', 'PROD-C07', 'Sensor C07');

CREATE TABLE resilimes.route_steps (product_id VARCHAR(256), step_index VARCHAR(256), step VARCHAR(256), capability VARCHAR(256), process_time_min VARCHAR(256), setup_family VARCHAR(256), step_no VARCHAR(256), operation VARCHAR(256), area VARCHAR(256), recipe VARCHAR(256), layer VARCHAR(256), rework VARCHAR(256));
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-A28', '0', 'DEP', 'cvd_oxide', '28', 'CVD_OX', '10', 'Deposition', 'Deposition', 'CVD_L1', 'L1', 'false');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-A28', '1', 'LITHO', 'litho_193nm', '75', 'LITHO_A', '20', 'Lithography', 'Lithography', 'LITHO_L1', 'L1', 'false');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-A28', '2', 'MEAS', 'overlay_cd', '20', 'OCD', '30', 'Metrology', 'Metrology', 'OCD_L1', 'L1', 'false');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-A28', '3', 'ETCH', 'etch_dielectric', '40', 'ETCH_D', '40', 'Etch', 'Etch', 'ETCH_L1', 'L1', 'false');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-A28', '4', 'CLEAN', 'wet_clean', '16', 'WET', '50', 'Clean', 'Clean', 'WET_L1', 'L1', 'false');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-A28', '5', 'CMP', 'cmp_oxide', '32', 'CMP_OX', '60', 'CMP', 'CMP', 'CMP_L1', 'L1', 'false');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-A28', '6', 'DEP-L2', 'cvd_oxide', '28', 'CVD_OX', '70', 'Deposition', 'Deposition', 'CVD_L2', 'L2', 'false');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-A28', '7', 'LITHO-L2', 'litho_193nm', '75', 'LITHO_A', '80', 'Lithography', 'Lithography', 'LITHO_L2', 'L2', 'false');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-A28', '8', 'MEAS-L2', 'overlay_cd', '20', 'OCD', '90', 'Metrology', 'Metrology', 'OCD_L2', 'L2', 'false');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-A28', '9', 'ETCH-L2', 'etch_dielectric', '40', 'ETCH_D', '100', 'Etch', 'Etch', 'ETCH_L2', 'L2', 'false');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-A28', '10', 'CLEAN-L2', 'wet_clean', '16', 'WET', '110', 'Clean', 'Clean', 'WET_L2', 'L2', 'false');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-A28', '11', 'CMP-L2', 'cmp_oxide', '32', 'CMP_OX', '120', 'CMP', 'CMP', 'CMP_L2', 'L2', 'false');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-B14', '0', 'DEP', 'cvd_oxide', '20', 'CVD_OX', '10', 'Deposition', 'Deposition', 'CVD_B14', 'M1', 'false');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-B14', '1', 'ETCH', 'etch_metal', '30', 'ETCH_M', '20', 'Etch', 'Etch', 'ETCH_M1', 'M1', 'false');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-B14', '2', 'CLEAN', 'wet_clean', '12', 'WET', '30', 'Clean', 'Clean', 'WET_B14', 'M1', 'false');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-B14', '3', 'DEP-2', 'cvd_oxide', '20', 'CVD_OX', '40', 'Deposition', 'Deposition', 'CVD_CAP', 'M1', 'false');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-C07', '0', 'LITHO', 'litho_193nm', '40', 'LITHO_C', '10', 'Lithography', 'Lithography', 'LITHO_C07', 'S1', 'false');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-C07', '1', 'ETCH', 'etch_dielectric', '24', 'ETCH_D', '20', 'Etch', 'Etch', 'ETCH_SNS', 'S1', 'false');
INSERT INTO resilimes.route_steps (product_id, step_index, step, capability, process_time_min, setup_family, step_no, operation, area, recipe, layer, rework) VALUES ('PROD-C07', '2', 'CMP', 'cmp_oxide', '45', 'CMP_OX', '30', 'CMP', 'CMP', 'CMP_SNS', 'S1', 'false');

CREATE TABLE resilimes.qtime_rule (rule_id VARCHAR(256), product_id VARCHAR(256), from_step VARCHAR(256), to_step VARCHAR(256), max_min VARCHAR(256));
INSERT INTO resilimes.qtime_rule (rule_id, product_id, from_step, to_step, max_min) VALUES ('QT-A28-CLEAN-DEP', 'PROD-A28', 'CLEAN', 'DEP-L2', '480');
INSERT INTO resilimes.qtime_rule (rule_id, product_id, from_step, to_step, max_min) VALUES ('QT-B14-CLEAN-DEP', 'PROD-B14', 'CLEAN', 'DEP-2', '480');

CREATE TABLE resilimes.reticle (reticle_id VARCHAR(256), product_id VARCHAR(256), layer VARCHAR(256), step VARCHAR(256));
INSERT INTO resilimes.reticle (reticle_id, product_id, layer, step) VALUES ('RET-A28-L1-1', 'PROD-A28', 'L1', 'LITHO');
INSERT INTO resilimes.reticle (reticle_id, product_id, layer, step) VALUES ('RET-A28-L1-2', 'PROD-A28', 'L1', 'LITHO');
INSERT INTO resilimes.reticle (reticle_id, product_id, layer, step) VALUES ('RET-A28-L2-1', 'PROD-A28', 'L2', 'LITHO-L2');
INSERT INTO resilimes.reticle (reticle_id, product_id, layer, step) VALUES ('RET-A28-L2-2', 'PROD-A28', 'L2', 'LITHO-L2');

CREATE TABLE resilimes.inhibit (inhibit_id VARCHAR(256), product_id VARCHAR(256), recipe VARCHAR(256), equipment_id VARCHAR(256));
INSERT INTO resilimes.inhibit (inhibit_id, product_id, recipe, equipment_id) VALUES ('INH-C07-LITHO01', 'PROD-C07', NULL, 'LITHO-01');
INSERT INTO resilimes.inhibit (inhibit_id, product_id, recipe, equipment_id) VALUES ('INH-L2-LITHO02', NULL, 'LITHO_L2', 'LITHO-02');

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
INSERT INTO resilimes.operators (operator_id, name, certified, shift) VALUES ('OP-02', 'L. Nguyen', 'litho_193nm,cvd_oxide,overlay_cd', 'A');
INSERT INTO resilimes.operators (operator_id, name, certified, shift) VALUES ('OP-03', 'M. Park', 'etch_dielectric,etch_metal,cmp_oxide', 'A');
INSERT INTO resilimes.operators (operator_id, name, certified, shift) VALUES ('OP-04', 'R. Singh', 'cmp_oxide,etch_metal,wet_clean', 'A');

CREATE TABLE resilimes.maintenance_logs (log_id VARCHAR(256), equipment_id VARCHAR(256), event_type VARCHAR(256), occurred_at VARCHAR(256), severity_code VARCHAR(256), description VARCHAR(256), estimated_repair_min VARCHAR(256), technician VARCHAR(256));
INSERT INTO resilimes.maintenance_logs (log_id, equipment_id, event_type, occurred_at, severity_code, description, estimated_repair_min, technician) VALUES ('M-9001', 'LITHO-02', 'FAULT', '2026-10-22T06:12:00Z', 'LASER_FAULT', 'Machine Litho-02 Down — laser source interlock tripped', '180', 'tech.kim');
INSERT INTO resilimes.maintenance_logs (log_id, equipment_id, event_type, occurred_at, severity_code, description, estimated_repair_min, technician) VALUES ('M-9002', 'LITHO-02', 'ALARM', '2026-10-22T06:05:00Z', 'TEMP_WARN', 'Scanner chamber temperature drift +2.1C before fault', '0', 'system');
INSERT INTO resilimes.maintenance_logs (log_id, equipment_id, event_type, occurred_at, severity_code, description, estimated_repair_min, technician) VALUES ('M-9003', 'DEP-01', 'PM_START', '2026-10-22T04:00:00Z', 'PM_CVD', 'Scheduled preventive maintenance window', '240', 'tech.nguyen');
INSERT INTO resilimes.maintenance_logs (log_id, equipment_id, event_type, occurred_at, severity_code, description, estimated_repair_min, technician) VALUES ('M-9004', 'ETCH-01', 'ALARM', '2026-10-21T22:14:00Z', 'RF_REFLECT', 'Transient RF reflection spike; auto-recovered', '0', 'system');
INSERT INTO resilimes.maintenance_logs (log_id, equipment_id, event_type, occurred_at, severity_code, description, estimated_repair_min, technician) VALUES ('M-9005', 'LITHO-01', 'PM_COMPLETE', '2026-10-18T08:00:00Z', 'PM_LITHO', 'Quarterly optics clean and calibration', '0', 'tech.park');
INSERT INTO resilimes.maintenance_logs (log_id, equipment_id, event_type, occurred_at, severity_code, description, estimated_repair_min, technician) VALUES ('M-9006', 'CMP-01', 'ALARM', '2026-10-21T11:02:00Z', 'PAD_WEAR', 'Pad wear near threshold; continue with monitoring', '0', 'system');
INSERT INTO resilimes.maintenance_logs (log_id, equipment_id, event_type, occurred_at, severity_code, description, estimated_repair_min, technician) VALUES ('M-9007', 'ETCH-02', 'FAULT', '2026-10-15T09:40:00Z', 'PUMP_DOWN', 'Roughing pump failure — repaired and returned to IDLE', '360', 'tech.kim');
INSERT INTO resilimes.maintenance_logs (log_id, equipment_id, event_type, occurred_at, severity_code, description, estimated_repair_min, technician) VALUES ('M-9008', 'LITHO-02', 'FAULT', '2026-10-10T16:20:00Z', 'STAGE_STALL', 'Wafer stage stall; parts replaced', '420', 'tech.nguyen');
INSERT INTO resilimes.maintenance_logs (log_id, equipment_id, event_type, occurred_at, severity_code, description, estimated_repair_min, technician) VALUES ('M-9009', 'DEP-01', 'PM_COMPLETE', '2026-10-22T06:20:00Z', 'PM_CVD', 'CVD chamber PM finished; tool is up for the 06:30 clock', '0', 'tech.nguyen');
