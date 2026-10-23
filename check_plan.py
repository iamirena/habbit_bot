from planner import DEFAULT_TASKS, build_plan, format_plan

print(format_plan(build_plan(DEFAULT_TASKS, energy=6, stress=5)))
print("-----")
print(format_plan(build_plan(DEFAULT_TASKS, energy=3, stress=8)))