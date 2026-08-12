class_name SagaRunAndGunBoss
extends SagaRunAndGunEnemy

signal phase_changed(phase: int)

var phase := 1

func _ready() -> void:
	super._ready()
	remove_from_group("run_and_gun_enemies")
	add_to_group("run_and_gun_boss")
	patrol_distance = 180.0
	chase_range = 520.0

func configure(options: Dictionary) -> void:
	var boss_options := options.duplicate()
	boss_options["role"] = "boss"
	super.configure(boss_options)
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
		_fire_pattern()
		shot_cooldown = maxf(0.35, 1.35 - phase * 0.25)

func _fire_pattern() -> void:
	var angles: Array[float] = [0.0]
	if phase == 2:
		angles = [-13.0, 0.0, 13.0]
	elif phase == 3:
		angles = [-26.0, -13.0, 0.0, 13.0, 26.0]
	var base_direction := global_position.direction_to(target.global_position)
	for angle in angles:
		var projectile := SagaRunAndGunProjectile.new()
		get_parent().add_child(projectile)
		projectile.global_position = global_position + Vector2(0, -8)
		projectile.configure({
			"direction": base_direction.rotated(deg_to_rad(angle)),
			"speed": projectile_speed * (1.0 + float(phase - 1) * 0.08),
			"damage": 1,
			"faction": faction,
			"weapon_id": "boss_phase_%d" % phase,
		})

func qa_set_phase(next_phase: int) -> void:
	phase = clampi(next_phase, 1, 3)

func attack_pattern_projectiles() -> int:
	return 1 if phase == 1 else (3 if phase == 2 else 5)
