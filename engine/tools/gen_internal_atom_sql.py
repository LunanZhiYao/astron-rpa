import json
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
meta_path = repo / "engine/components/astronverse-internal/meta.json"
out_path = repo / "docker/volumes/mysql/patch_c_atom_meta_internal.sql"

meta = json.loads(meta_path.read_text(encoding="utf-8"))
lines = [
    "-- 内部组件：原子元数据（需在已有库执行时合并进 atomCommon，见 init 脚本或下方说明）",
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
