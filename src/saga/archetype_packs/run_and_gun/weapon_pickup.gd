class_name SagaRunAndGunWeaponPickup
extends Area2D

var weapon_id := "spread"
var ammo := 12
var consumed := false

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
	var visual := Polygon2D.new()
	visual.polygon = PackedVector2Array([
		Vector2(-19, -8), Vector2(8, -8), Vector2(8, -13),
		Vector2(19, -13), Vector2(19, 1), Vector2(2, 1),
		Vector2(2, 12), Vector2(-9, 12), Vector2(-9, 1), Vector2(-19, 1),
	])
	visual.color = Color("ffd45a") if weapon_id == "spread" else Color("ff8b4f")
	add_child(visual)

func collect(body: Node) -> void:
	if consumed or not body.is_in_group("run_and_gun_player") or not body.has_method("equip_weapon"):
		return
	if not body.equip_weapon(weapon_id, ammo):
		return
	consumed = true
	Sfx.play("pickup")
	queue_free()
