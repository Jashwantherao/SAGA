class_name SagaRunAndGunHazard
extends Area2D

var damage := 1

func _ready() -> void:
	add_to_group("run_and_gun_hazards")
	collision_layer = 0
	collision_mask = 1
	body_entered.connect(_on_body_entered)

func configure(options: Dictionary) -> void:
	damage = int(options.get("damage", damage))
	var size := Vector2(float(options.get("width", 80.0)), 24.0)
	var collision := CollisionShape2D.new()
	var rectangle := RectangleShape2D.new()
	rectangle.size = size
	collision.shape = rectangle
	add_child(collision)
	var visual := Polygon2D.new()
	visual.polygon = PackedVector2Array([
		Vector2(-size.x / 2.0, size.y / 2.0),
		Vector2(-size.x * 0.25, -size.y / 2.0),
		Vector2(0, size.y / 2.0),
		Vector2(size.x * 0.25, -size.y / 2.0),
		Vector2(size.x / 2.0, size.y / 2.0),
	])
	visual.color = Color("ff4f5e")
	add_child(visual)

func _on_body_entered(body: Node) -> void:
	if body.has_method("take_damage") and body.is_in_group("run_and_gun_player"):
		body.take_damage(damage)

