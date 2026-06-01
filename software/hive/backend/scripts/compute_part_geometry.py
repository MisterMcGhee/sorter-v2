import os
import sys
import time
import json
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.profile_engine import db as profile_db
from app.services.profile_engine import ldraw_geometry as lg

DEFAULT_LDRAW = os.path.join(os.path.dirname(__file__), "..", "ldraw_lib", "ldraw")
DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "data", "profile_builder", "parts.db")


def main():
    ldraw_root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LDRAW)
    db_path = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else DEFAULT_DB)
    print(f"ldraw: {ldraw_root}")
    print(f"db:    {db_path}")

    conn = sqlite3.connect(db_path)
    profile_db.runMigrations(conn)

    print("building LDraw file index...")
    index = lg.buildFileIndex(ldraw_root)
    print(f"  {len(index)} resolvable .dat files")
    resolver = lg._Resolver(index)

    rows = conn.execute("SELECT part_num, external_ids FROM parts").fetchall()
    total = len(rows)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    direct = parent = none = 0
    for i, (part_num, ext_json) in enumerate(rows):
        ext = json.loads(ext_json) if ext_json else {}
        ldraw_ids = [str(x) for x in ext.get("LDraw", [])]
        geom = lg.resolveGeometry(resolver, part_num, ldraw_ids)
        if geom:
            profile_db.upsertPartGeometry(conn, part_num, geom, now)
            if geom["geometry_source"] == "direct":
                direct += 1
            else:
                parent += 1
        else:
            none += 1
        if (i + 1) % 5000 == 0:
            conn.commit()
            print(f"  {i+1}/{total}  direct={direct} parent={parent} none={none}")
    conn.commit()

    have = direct + parent
    print(f"\nDONE: {have}/{total} parts with geometry ({100*have/total:.1f}%)")
    print(f"  direct={direct}  parent={parent}  none={none}")

    print("\nspot-check:")
    for pid in ["3001", "3005", "3023", "3068b", "973pb2833", "3001pr0042"]:
        g = profile_db.getPartGeometry(conn, pid)
        if g:
            print(f"  {pid:14s} {g['bbox_x_mm']}x{g['bbox_y_mm']}x{g['bbox_z_mm']}mm "
                  f"ext={g['max_extent_mm']} vol={g['volume_mm3']} "
                  f"src={g['geometry_source']} parent={g['physical_parent_part_num']}")
        else:
            print(f"  {pid:14s} (none)")


if __name__ == "__main__":
    main()
