extends Node

const SCHEMA_VERSION := 1
const UPGRADE_TRACKS := ["firepower", "mobility", "vitality"]
const MAX_UPGRADE_LEVEL := 3

var profile: Dictionary = {}
var save_path := "user://saga_campaign_profile.json"
var last_load_status := "new"

func _ready() -> void:
	if "--objective-probe" in OS.get_cmdline_user_args() or "--campaign-probe" in OS.get_cmdline_user_args():
		save_path = "user://saga_campaign_profile.qa.json"
	reset_profile(false)
	if FileAccess.file_exists(save_path):
		load_profile()

func _default_profile() -> Dictionary:
	return {
		"schema_version": SCHEMA_VERSION,
		"currency": 0,
		"xp": 0,
		"upgrades": {"firepower": 0, "mobility": 0, "vitality": 0},
		"unlocked_weapons": ["pulse"],
		"claimed_rewards": [],
		"last_level": 0,
	}

func reset_profile(persist: bool = false) -> void:
	profile = _default_profile()
	last_load_status = "reset"
	if persist:
		save_profile()

func _valid_profile(candidate: Variant) -> bool:
	if typeof(candidate) != TYPE_DICTIONARY:
		return false
	var value := candidate as Dictionary
	if int(value.get("schema_version", -1)) != SCHEMA_VERSION:
		return false
	if int(value.get("currency", -1)) < 0 or int(value.get("xp", -1)) < 0:
		return false
	var upgrades := value.get("upgrades", {}) as Dictionary
	for track in UPGRADE_TRACKS:
		var level := int(upgrades.get(track, -1))
		if level < 0 or level > MAX_UPGRADE_LEVEL:
			return false
	if typeof(value.get("unlocked_weapons", [])) != TYPE_ARRAY or typeof(value.get("claimed_rewards", [])) != TYPE_ARRAY:
		return false
	return true

func save_profile() -> bool:
	if not _valid_profile(profile):
		last_load_status = "save_rejected"
		return false
	var temporary := save_path + ".tmp"
	var backup := save_path + ".bak"
	var file := FileAccess.open(temporary, FileAccess.WRITE)
	if file == null:
		last_load_status = "save_failed"
		return false
	file.store_string(JSON.stringify(profile))
	file.close()
	if FileAccess.file_exists(backup):
		DirAccess.remove_absolute(backup)
	if FileAccess.file_exists(save_path):
		if DirAccess.rename_absolute(save_path, backup) != OK:
			last_load_status = "save_failed"
			return false
	if DirAccess.rename_absolute(temporary, save_path) != OK:
		if FileAccess.file_exists(backup):
			DirAccess.rename_absolute(backup, save_path)
		last_load_status = "save_failed"
		return false
	if FileAccess.file_exists(backup):
		DirAccess.remove_absolute(backup)
	last_load_status = "saved"
	return true

func load_profile() -> bool:
	if not FileAccess.file_exists(save_path):
		reset_profile(false)
		last_load_status = "new"
		return false
	var file := FileAccess.open(save_path, FileAccess.READ)
	if file == null:
		reset_profile(false)
		last_load_status = "reset_corrupt"
		return false
	var parser := JSON.new()
	var parse_error := parser.parse(file.get_as_text())
	file.close()
	var parsed: Variant = parser.data if parse_error == OK else null
	if not _valid_profile(parsed):
		reset_profile(false)
		last_load_status = "reset_corrupt"
		return false
	profile = (parsed as Dictionary).duplicate(true)
	last_load_status = "loaded"
	return true

func begin_level(level_index: int) -> void:
	var next_level := maxi(0, level_index)
	if int(profile.get("last_level", -1)) != next_level:
		profile["last_level"] = next_level
		save_profile()

func award_level(reward_id: String, currency: int, xp: int) -> bool:
	var claimed := profile.get("claimed_rewards", []) as Array
	if reward_id in claimed:
		return false
	claimed.append(reward_id)
	profile["claimed_rewards"] = claimed
	profile["currency"] = int(profile.get("currency", 0)) + maxi(0, currency)
	profile["xp"] = int(profile.get("xp", 0)) + maxi(0, xp)
	return save_profile()

func purchase_upgrade(track: String, cost: int) -> bool:
	if track not in UPGRADE_TRACKS or cost < 0 or int(profile.get("currency", 0)) < cost:
		return false
	var upgrades := profile.get("upgrades", {}) as Dictionary
	var current := int(upgrades.get(track, 0))
	if current >= MAX_UPGRADE_LEVEL:
		return false
	profile["currency"] = int(profile.get("currency", 0)) - cost
	upgrades[track] = current + 1
	profile["upgrades"] = upgrades
	return save_profile()

func unlock_weapon(weapon_id: String) -> void:
	if weapon_id not in ["pulse", "spread", "launcher"]:
		return
	var unlocked := profile.get("unlocked_weapons", []) as Array
	if weapon_id not in unlocked:
		unlocked.append(weapon_id)
		profile["unlocked_weapons"] = unlocked
		save_profile()

func apply_to_player(player: Node) -> void:
	if player.has_method("apply_progression"):
		player.apply_progression(
			profile.get("upgrades", {}) as Dictionary,
			profile.get("unlocked_weapons", []) as Array
		)

func snapshot() -> Dictionary:
	var result := profile.duplicate(true)
	result["last_load_status"] = last_load_status
	return result

func qa_zero_memory() -> void:
	profile["currency"] = 0
	profile["xp"] = 0
	profile["upgrades"] = {"firepower": 0, "mobility": 0, "vitality": 0}

func qa_corrupt_save() -> void:
	var file := FileAccess.open(save_path, FileAccess.WRITE)
	if file != null:
		file.store_string("{broken save")
		file.close()
