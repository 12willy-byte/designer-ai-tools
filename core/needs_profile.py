"""Owner-needs cognition for the automated design pipeline."""
import json
import os

from core.design_schema import normalize_conditions


SCHEMA_VERSION = "needs_profile.v1"


def build_needs_profile(conditions, space_profile=None):
    """Build a structured understanding of the owner and design needs."""
    normalized = normalize_conditions(conditions or {})
    family = normalized.get("family") or {}
    style = normalized.get("style") or {}
    budget = normalized.get("budget") or {}
    room_requirements = _room_requirements(normalized)

    profile = {
        "schema_version": SCHEMA_VERSION,
        "resident_profile": {
            "residents": family.get("residents", ""),
            "composition": family.get("composition", ""),
            "children_ages": family.get("children_ages", ""),
            "elderly": family.get("elderly", ""),
            "pets": family.get("pets", ""),
        },
        "lifestyle": {
            "work_from_home": family.get("work_from_home", ""),
            "entertain_frequency": family.get("entertain_frequency", ""),
            "cooking_frequency": family.get("cooking_frequency", ""),
            "dining_habit": family.get("dining_habit", ""),
            "movement_preference": family.get("movement_preference", ""),
            "storage_need": family.get("storage_need", ""),
            "hobbies": family.get("hobbies", ""),
        },
        "style_preferences": {
            "primary_style": style.get("primary_style", ""),
            "color_tone": style.get("color_tone", ""),
            "keywords": style.get("keywords", ""),
            "floor_material": style.get("floor_material", ""),
            "wall_material": style.get("wall_material", ""),
            "ceiling_type": style.get("ceiling_type", ""),
        },
        "budget": budget,
        "room_requirements": room_requirements,
        "special_requirements": normalized.get("special_requirements") or {},
    }
    profile["priorities"] = infer_need_priorities(profile)
    profile["observations"] = build_needs_observations(profile, space_profile=space_profile)
    profile["questions_to_confirm"] = build_needs_questions(profile, space_profile=space_profile)
    profile["readiness"] = evaluate_needs_profile(profile)
    return profile


def build_needs_profile_from_file(conditions_json_path, space_profile=None, output_path=None):
    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)
    profile = build_needs_profile(conditions, space_profile=space_profile)
    if output_path:
        save_needs_profile(profile, output_path)
    return profile


def save_needs_profile(profile, output_path):
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    return output_path


def build_needs_cognition_package(conditions, output_dir, space_profile=None):
    """Write the M1 needs-cognition artifacts and return their paths."""
    os.makedirs(output_dir, exist_ok=True)
    profile = build_needs_profile(conditions, space_profile=space_profile)
    profile_path = save_needs_profile(profile, os.path.join(output_dir, "needs_profile.json"))

    observations_path = os.path.join(output_dir, "needs_observations.json")
    with open(observations_path, "w", encoding="utf-8") as f:
        json.dump(profile["observations"], f, ensure_ascii=False, indent=2)

    questions_path = os.path.join(output_dir, "needs_questions_to_confirm.json")
    with open(questions_path, "w", encoding="utf-8") as f:
        json.dump(profile["questions_to_confirm"], f, ensure_ascii=False, indent=2)

    return {
        "needs_profile": profile_path,
        "needs_observations": observations_path,
        "needs_questions_to_confirm": questions_path,
        "profile": profile,
    }


def infer_need_priorities(profile):
    lifestyle = profile.get("lifestyle") or {}
    style = profile.get("style_preferences") or {}
    room_requirements = profile.get("room_requirements") or []
    priorities = []

    storage_need = str(lifestyle.get("storage_need") or "")
    if any(word in storage_need for word in ("高", "强", "多")):
        priorities.append({"key": "storage", "label": "高收纳", "reason": "业主明确提出较高收纳需求。"})

    cooking = str(lifestyle.get("cooking_frequency") or "")
    if any(word in cooking for word in ("高", "每天", "经常", "中餐")):
        priorities.append({"key": "kitchen_efficiency", "label": "高频厨房", "reason": "做饭频率较高，厨房效率优先。"})

    if lifestyle.get("work_from_home"):
        priorities.append({"key": "work_from_home", "label": "在家办公", "reason": "需要安静、照明和收纳稳定的工作区。"})

    keywords = str(style.get("keywords") or "")
    if keywords:
        priorities.append({"key": "style_keywords", "label": keywords, "reason": "业主提供了明确风格关键词。"})

    for item in room_requirements:
        text = " ".join(str(v) for v in (item.get("requirements") or {}).values())
        if any(word in text for word in ("亲子", "儿童", "老人", "宠物")):
            priorities.append({"key": "family_safety", "label": "家庭友好", "reason": f"{item.get('room')} 包含家庭友好需求。"})

    return priorities


def build_needs_observations(profile, space_profile=None):
    observations = []
    lifestyle = profile.get("lifestyle") or {}
    resident = profile.get("resident_profile") or {}
    budget = profile.get("budget") or {}

    if resident.get("residents") or resident.get("composition"):
        observations.append(f"常住情况：{resident.get('residents') or '人数未知'}，{resident.get('composition') or '成员构成待确认'}。")
    if lifestyle.get("storage_need"):
        observations.append(f"收纳需求：{lifestyle['storage_need']}，后续布局需预留系统收纳。")
    if lifestyle.get("cooking_frequency"):
        observations.append(f"烹饪习惯：{lifestyle['cooking_frequency']}，厨房动线和台面长度需要重点校验。")
    if budget.get("total_budget"):
        observations.append(f"预算总额约 {budget['total_budget']}，可进入预算区间估算。")

    if space_profile:
        readiness = space_profile.get("readiness") or {}
        if "layout_draft" not in readiness.get("ready_for", []):
            observations.append("空间对象尚未满足自动布局草案条件，需求判断只能进入概念提案。")

    return observations


def build_needs_questions(profile, space_profile=None):
    questions = []
    resident = profile.get("resident_profile") or {}
    lifestyle = profile.get("lifestyle") or {}
    style = profile.get("style_preferences") or {}
    budget = profile.get("budget") or {}

    if not resident.get("residents") and not resident.get("composition"):
        questions.append({"category": "resident", "question": "请确认常住人数和家庭成员构成。", "required": True})
    if not lifestyle.get("storage_need"):
        questions.append({"category": "lifestyle", "question": "请确认收纳强度和重点收纳物品。", "required": False})
    if not lifestyle.get("cooking_frequency"):
        questions.append({"category": "lifestyle", "question": "请确认做饭频率、是否高频中餐。", "required": False})
    if not style.get("primary_style") and not style.get("keywords"):
        questions.append({"category": "style", "question": "请确认偏好的整体风格或不喜欢的风格。", "required": True})
    if not budget.get("total_budget"):
        questions.append({"category": "budget", "question": "请确认总预算或预算区间。", "required": True})

    if space_profile:
        for question in space_profile.get("questions_to_confirm", []):
            if question.get("required"):
                questions.append({
                    "category": "space_dependency",
                    "question": question.get("question", ""),
                    "required": True,
                })

    return questions


def evaluate_needs_profile(profile):
    blocking = []
    warnings = []
    unknowns = []
    resident = profile.get("resident_profile") or {}
    style = profile.get("style_preferences") or {}
    budget = profile.get("budget") or {}

    if not resident.get("residents") and not resident.get("composition"):
        blocking.append("缺少常住人口/家庭构成")
    if not style.get("primary_style") and not style.get("keywords"):
        blocking.append("缺少风格偏好")
    if not budget.get("total_budget"):
        warnings.append("缺少总预算，预算和材料档次只能粗略估算")
    if not profile.get("room_requirements"):
        unknowns.append("缺少各空间具体需求")

    score = 100 - len(blocking) * 30 - len(warnings) * 12 - len(unknowns) * 8
    score = max(0, min(100, score))
    ready_for = []
    if not blocking:
        ready_for.append("concept_package")
    if not blocking and budget.get("total_budget"):
        ready_for.append("budget_estimate")

    return {
        "score": score,
        "ready_for": ready_for,
        "blocking_issues": blocking,
        "warnings": warnings,
        "unknowns": unknowns,
    }


def _room_requirements(conditions):
    result = []
    for name, requirements in (conditions.get("rooms_requirements") or {}).items():
        result.append({"room": name, "requirements": requirements or {}})
    return result
