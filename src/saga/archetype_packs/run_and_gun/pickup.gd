class_name SagaRunAndGunPickup
extends Area2D

var amount := 1
var consumed := false

func _ready() -> void:
	add_to_group("run_and_gun_pickups")
	collision_layer = 0
	collision_mask = 1
	body_entered.connect(_on_body_entered)
	var collision := CollisionShape2D.new()
	var circle := CircleShape2D.new()
	circle.radius = 17.0
	collision.shape = circle
	add_child(collision)
	var visual := Polygon2D.new()
	visual.polygon = PackedVector2Array([
		Vector2(-15, -7), Vector2(-7, -7), Vector2(-7, -15), Vector2(7, -15),
		Vector2(7, -7), Vector2(15, -7), Vector2(15, 7), Vector2(7, 7),
		Vector2(7, 15), Vector2(-7, 15), Vector2(-7, 7), Vector2(-15, 7),
	])
	visual.color = Color("62f5a3")
	add_child(visual)

func configure(options: Dictionary) -> void:
	amount = int(options.get("amount", amount))

func _on_body_entered(body: Node) -> void:
	if consumed or not body.is_in_group("run_and_gun_player") or not body.has_method("heal"):
		return
	consumed = true
	body.heal(amount)
	Sfx.play("pickup")
	queue_free()

