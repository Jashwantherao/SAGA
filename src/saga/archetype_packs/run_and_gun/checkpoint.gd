class_name SagaRunAndGunCheckpoint
extends Area2D

signal activated(checkpoint: Node)

var active := false
var checkpoint_sprite: Sprite2D

func _ready() -> void:
	add_to_group("run_and_gun_checkpoints")
	collision_layer = 0
	collision_mask = 1
	var shape := CollisionShape2D.new()
	var rectangle := RectangleShape2D.new()
	rectangle.size = Vector2(42, 70)
	shape.shape = rectangle
	add_child(shape)
	body_entered.connect(activate)

func activate(body: Node) -> void:
	if active or not body.has_method("set_checkpoint"):
		return
	active = true
	body.set_checkpoint(global_position + Vector2(0, -36))
	if is_instance_valid(checkpoint_sprite):
		checkpoint_sprite.modulate = Color("76ff9f")
		Anim.pop(checkpoint_sprite)
	Sfx.play("pickup")
	activated.emit(self)
