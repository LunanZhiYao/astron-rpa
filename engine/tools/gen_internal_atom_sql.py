import json
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
meta_path = repo / "engine/components/astronverse-internal/meta.json"
out_path = repo / "docker/volumes/mysql/patch_c_atom_meta_internal.sql"

meta = json.loads(meta_path.read_text(encoding="utf-8"))
lines = [
    "-- Internal 组件（astronverse-internal）：原子元数据（需在已有库执行时合并进 atomCommon，见 init 脚本或下方说明）",
    "-- 说明：左侧原子树来自 atom_key = atomCommon 的 JSON（atomicTree / atomicTreeExtend），",
    "-- 仅插入本表其它行不会出现菜单；必须同步更新 atomCommon（见下方 UPDATE）。",
    "-- robot-service 对个人版租户会隐藏 enterprise 相关节点，与 Internal 分组无关。",
    "",
]
for i, (k, row) in enumerate(meta.items(), 1001):
    js = json.dumps(row, ensure_ascii=False, separators=(",", ": "))
    esc = js.replace("'", "''")
    ak = k.replace("'", "''")
    line = (
        f"INSERT INTO `c_atom_meta_new` (`atom_key`,`atom_content`,`sort`,`create_time`,`update_time`) "
        f"VALUES ('{ak}','{esc}',NULL,NOW(),NOW()) "
        f"ON DUPLICATE KEY UPDATE `atom_content`=VALUES(`atom_content`),`update_time`=NOW();"
    )
    lines.append(line)

ATOMCOMMON_UPDATE = """
-- 在「扩展原子」页签展示分组：向 atomCommon.atomicTreeExtend 首部插入 internal 分组（与仓库 init 中片段一致）。
-- 仅当库中 atomCommon 仍为旧版（atomicTreeExtend 以 AI 开头）时执行；若已包含 internal 请勿重复执行。
UPDATE `c_atom_meta_new` SET `atom_content` = REPLACE(
  `atom_content`,
  'atomicTreeExtend": [{"key": "ai", "title": "AI", "atomics":',
  'atomicTreeExtend": [{"key": "internal", "title": "\\\\u5185\\\\u90e8\\\\u7ec4\\\\u4ef6", "atomics": [{"key": "Internal.wecom_group_message", "title": "\\\\u4f01\\\\u4e1a\\\\u5fae\\\\u4fe1\\\\u7fa4\\\\u6d88\\\\u606f", "icon": "wecom-robot-message"}, {"key": "Internal.yunshang_lunan_message", "title": "\\\\u4e91\\\\u4e0a\\\\u9c81\\\\u5357\\\\u6d88\\\\u606f\\\\u63a8\\\\u9001", "icon": "cloud-lunan-message"}]}, {"key": "ai", "title": "AI", "atomics":'
), `update_time` = NOW()
WHERE `atom_key` = 'atomCommon'
  AND `atom_content` LIKE '%atomicTreeExtend": [{"key": "ai", "title": "AI", "atomics":%'
  AND `atom_content` NOT LIKE '%"key": "internal"%';

-- 修复：此前将 key 前缀改为 Internal 时误把分组显示名 title 也改成了英文，此处恢复为「内部组件」
UPDATE `c_atom_meta_new` SET `atom_content` = REPLACE(
  `atom_content`,
  '"key": "internal", "title": "Internal", "atomics":',
  '"key": "internal", "title": "\\\\u5185\\\\u90e8\\\\u7ec4\\\\u4ef6", "atomics":'
), `update_time` = NOW()
WHERE `atom_key` = 'atomCommon'
  AND `atom_content` LIKE '%"key": "internal", "title": "Internal", "atomics":%';
""".lstrip()

lines.append(ATOMCOMMON_UPDATE)

out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Wrote {out_path}")

# init 全量脚本：带 id，与仓库 init_c_atom_meta_new_data.sql 风格一致
init_lines = []
ts = "2026-04-15 12:00:00"
for i, (k, row) in enumerate(meta.items(), 1001):
    js = json.dumps(row, ensure_ascii=False, separators=(", ", ": "))
    esc = js.replace("'", "''")
    ak = k.replace("'", "''")
    init_lines.append(
        "INSERT INTO `c_atom_meta_new` (`id`,`atom_key`,`atom_content`,`sort`,`create_time`,`update_time`)  "
        f"VALUES ('{i}','{ak}','{esc}',NULL,'{ts}','{ts}');"
    )
init_snip = repo / "docker/volumes/mysql/_internal_atoms_for_init_append.sql"
init_snip.write_text("\n".join(init_lines) + "\n", encoding="utf-8")
print(f"Wrote {init_snip}")
