extends Node

const SCHEMA_VERSION := 1
const SAVE_PATH := "user://saga_action_rpg_save.json"
const TEMP_PATH := "user://saga_action_rpg_save.tmp"
const BACKUP_PATH := "user://saga_action_rpg_save.bak"
const QA_SAVE_PATH := "user://saga_action_rpg_qa_save.json"
const QA_TEMP_PATH := "user://saga_action_rpg_qa_save.tmp"
const QA_BACKUP_PATH := "user://saga_action_rpg_qa_save.bak"

var data: Dictionary = {}

func _paths() -> Dictionary:
	if "--objective-probe" in OS.get_cmdline_user_args():
		return {"save": QA_SAVE_PATH, "temp": QA_TEMP_PATH, "backup": QA_BACKUP_PATH}
	return {"save": SAVE_PATH, "temp": TEMP_PATH, "backup": BACKUP_PATH}

func _ready() -> void:
	load_profile()

func defaults() -> Dictionary:
	return {
		"schema_version": SCHEMA_VERSION,
		"room_index": 0,
		"hero_position": [150.0, 320.0],
		"hero_hp": 5,
		"sparks": 0,
		"items": {},
		"quest_stage": "collect_sparks",
		"dash_unlocked": false,
		"boss_defeated": false,
		"collected_pickups": [],
		"cleared_enemies": []
	}

func reset() -> void:
	data = defaults()

func snapshot() -> Dictionary:
	if data.is_empty():
		reset()
	return data.duplicate(true)

func checkpoint(next_data: Dictionary) -> bool:
	var normalized := defaults()
	for key in normalized:
		if next_data.has(key):
			normalized[key] = next_data[key]
	normalized["schema_version"] = SCHEMA_VERSION
	data = normalized
	return save_profile()

func save_profile() -> bool:
	var paths := _paths()
	var save_path := str(paths["save"])
	var temp_path := str(paths["temp"])
	var backup_path := str(paths["backup"])
	var file := FileAccess.open(temp_path, FileAccess.WRITE)
	if file == null:
		return false
	file.store_string(JSON.stringify(snapshot()))
	file.close()
	if FileAccess.file_exists(save_path):
		DirAccess.copy_absolute(ProjectSettings.globalize_path(save_path), ProjectSettings.globalize_path(backup_path))
		DirAccess.remove_absolute(ProjectSettings.globalize_path(save_path))
	var result := DirAccess.rename_absolute(ProjectSettings.globalize_path(temp_path), ProjectSettings.globalize_path(save_path))
	if result != OK and FileAccess.file_exists(backup_path):
		DirAccess.copy_absolute(ProjectSettings.globalize_path(backup_path), ProjectSettings.globalize_path(save_path))
	return result == OK

func load_profile() -> bool:
	var paths := _paths()
	for path in [str(paths["save"]), str(paths["backup"])]:
		if not FileAccess.file_exists(path):
			continue
		var file := FileAccess.open(path, FileAccess.READ)
		if file == null:
			continue
		var parsed = JSON.parse_string(file.get_as_text())
		file.close()
		if parsed is Dictionary and int(parsed.get("schema_version", -1)) == SCHEMA_VERSION:
			checkpoint_memory(parsed)
			return true
	reset()
	return false

func checkpoint_memory(next_data: Dictionary) -> void:
	var normalized := defaults()
	for key in normalized:
		if next_data.has(key):
			normalized[key] = next_data[key]
	normalized["schema_version"] = SCHEMA_VERSION
	data = normalized
