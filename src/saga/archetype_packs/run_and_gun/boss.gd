class_name SagaRunAndGunBoss
extends SagaRunAndGunEnemy

signal phase_changed(phase: int)

var phase := 1
var shot_cooldown := 1.2
var projectile_speed := 460.0

func _ready() -> void:
	super._ready()
	remove_from_group("run_and_gun_enemies")
	add_to_group("run_and_gun_boss")
	patrol_distance = 180.0
	chase_range = 520.0

func configure(options: Dictionary) -> void:
	super.configure(options)
	projectile_speed = float(options.get("projectile_speed", projectile_speed))

func _physics_process(delta: float) -> void:
	super._physics_process(delta)
	if "--autoplay" in OS.get_cmdline_user_args():
		return
	if health <= 0 or not is_instance_valid(target):
		return
	var wanted_phase := 3 if health <= max_health / 3 else (2 if health <= max_health * 2 / 3 else 1)
	if wanted_phase != phase:
		phase = wanted_phase
		move_speed *= 1.18
		phase_changed.emit(phase)
	shot_cooldown -= delta
	if shot_cooldown <= 0.0:
		_fire_at_target()
		shot_cooldown = maxf(0.35, 1.35 - phase * 0.25)

func _fire_at_target() -> void:
	var projectile := SagaRunAndGunProjectile.new()
	get_parent().add_child(projectile)
	projectile.global_position = global_position + Vector2(0, -8)
	projectile.configure({
		"direction": global_position.direction_to(target.global_position),
		"speed": projectile_speed,
		"damage": 1,
		"faction": faction,
	})
