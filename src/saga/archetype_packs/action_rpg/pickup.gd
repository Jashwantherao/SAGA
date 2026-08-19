class_name SagaActionRpgPickup
extends Area2D

signal collected(pickup_id: String, kind: String, amount: int)

var pickup_id := "pickup"
var kind := "sparks"
var amount := 1
var consumed := false

func _ready() -> void:
	add_to_group("action_rpg_pickups")
	collision_layer = 8
	collision_mask = 2
	var collision := CollisionShape2D.new()
	var shape := CircleShape2D.new()
	shape.radius = 12.0
	collision.shape = shape
	add_child(collision)
	var visual := Polygon2D.new()
	visual.polygon = PackedVector2Array([Vector2(0, -13), Vector2(11, 0), Vector2(0, 13), Vector2(-11, 0)])
	visual.color = Color("ffd56b")
	add_child(visual)
	body_entered.connect(_on_body_entered)

func configure(data: Dictionary) -> void:
	pickup_id = str(data.get("id", pickup_id))
	kind = str(data.get("kind", kind))
	amount = int(data.get("amount", amount))

func collect_for(player: Node) -> bool:
	if consumed or not player.is_in_group("action_rpg_player"):
		return false
	consumed = true
	visible = false
	monitoring = false
	collected.emit(pickup_id, kind, amount)
	return true

func _on_body_entered(body: Node) -> void:
	collect_for(body)
