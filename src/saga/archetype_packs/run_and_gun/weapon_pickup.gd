class_name SagaRunAndGunWeaponPickup
extends Area2D

var weapon_id := "spread"
var ammo := 12
var consumed := false
var _visual_root: Node2D
var _hover_time := 0.0

func _ready() -> void:
	add_to_group("run_and_gun_weapon_pickups")
	collision_layer = 0
	collision_mask = 1
	body_entered.connect(collect)
	var collision := CollisionShape2D.new()
	var rectangle := RectangleShape2D.new()
	rectangle.size = Vector2(38, 24)
	collision.shape = rectangle
	add_child(collision)

func configure(options: Dictionary) -> void:
	weapon_id = str(options.get("weapon", weapon_id))
	ammo = int(options.get("ammo", ammo))
	_visual_root = Node2D.new()
	add_child(_visual_root)
	var accent := Color("ffd45a") if weapon_id == "spread" else Color("ff8b4f")
	_add_panel(PackedVector2Array([
		Vector2(-30, -13), Vector2(-21, -23), Vector2(21, -23),
		Vector2(30, -13), Vector2(30, 13), Vector2(21, 23),
		Vector2(-21, 23), Vector2(-30, 13),
	]), Color("111b35"))
	_add_panel(PackedVector2Array([
		Vector2(-25, -10), Vector2(-18, -18), Vector2(18, -18),
		Vector2(25, -10), Vector2(25, 10), Vector2(18, 18),
		Vector2(-18, 18), Vector2(-25, 10),
	]), Color(accent, 0.34))
	# A compact side-on weapon silhouette inside an illuminated armory pod.
	_add_panel(PackedVector2Array([
		Vector2(-18, -6), Vector2(8, -6), Vector2(8, -10),
		Vector2(21, -10), Vector2(21, -2), Vector2(5, 1),
		Vector2(0, 12), Vector2(-8, 12), Vector2(-6, 1), Vector2(-18, 1),
	]), Color("eaf9ff"))
	for x in [-17.0, -7.0, 3.0, 13.0]:
		_add_panel(PackedVector2Array([
			Vector2(x, 16), Vector2(x + 6, 16),
			Vector2(x + 6, 19), Vector2(x, 19),
		]), accent)
	var ring := Line2D.new()
	ring.width = 2.0
	ring.default_color = Color(accent, 0.8)
	ring.closed = true
	ring.points = PackedVector2Array([
		Vector2(-34, 0), Vector2(-24, -25), Vector2(0, -31),
		Vector2(24, -25), Vector2(34, 0), Vector2(24, 25),
		Vector2(0, 31), Vector2(-24, 25),
	])
	_visual_root.add_child(ring)

func _process(delta: float) -> void:
	if not is_instance_valid(_visual_root):
		return
	_hover_time += delta
	_visual_root.position.y = sin(_hover_time * 2.4) * 3.0
	_visual_root.modulate.a = 0.9 + sin(_hover_time * 3.2) * 0.1

func _add_panel(points: PackedVector2Array, color: Color) -> void:
	var panel := Polygon2D.new()
	panel.polygon = points
	panel.color = color
	_visual_root.add_child(panel)

func collect(body: Node) -> void:
	if consumed or not body.is_in_group("run_and_gun_player") or not body.has_method("equip_weapon"):
		return
	if not body.equip_weapon(weapon_id, ammo):
		return
	CampaignProfile.unlock_weapon(weapon_id)
	consumed = true
	Sfx.play("pickup")
	queue_free()
