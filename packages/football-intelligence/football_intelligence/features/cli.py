from __future__ import annotations
import argparse, json
from pathlib import Path
from football_intelligence.distribution.runtime import RuntimeBuildHandle
from .store import build_features, replay_feature_build, validate_active_features, validate_feature_build
def main(argv=None):
    p=argparse.ArgumentParser(prog="python -m football_intelligence.features"); s=p.add_subparsers(dest="cmd",required=True)
    b=s.add_parser("build"); b.add_argument("--canonical-root",type=Path,required=True); b.add_argument("--feature-root",type=Path,required=True); b.add_argument("--feature-build-id",required=True); b.add_argument("--built-at",required=True)
    v=s.add_parser("validate"); v.add_argument("--canonical-root",type=Path,required=True); v.add_argument("--feature-build",type=Path,required=True)
    r=s.add_parser("replay"); r.add_argument("--canonical-root",type=Path,required=True); r.add_argument("--source-feature-build",type=Path,required=True); r.add_argument("--destination",type=Path,required=True)
    status=s.add_parser("status"); status.add_argument("--canonical-root",type=Path,required=True); status.add_argument("--feature-root",type=Path,required=True)
    args=p.parse_args(argv)
    try:
        handle=RuntimeBuildHandle(args.canonical_root)
        if args.cmd=="build": result=build_features(handle,args.feature_root,feature_build_id=args.feature_build_id,built_at=args.built_at)
        elif args.cmd=="validate": result=validate_feature_build(args.feature_build,handle)
        elif args.cmd=="replay": result=replay_feature_build(args.source_feature_build,handle,args.destination)
        else: result=validate_active_features(args.feature_root,handle)
        print(json.dumps({"feature_build_id":result["feature_build_id"],"row_counts":result["row_counts"]},sort_keys=True)); return 0
    except Exception as exc: print(f"FI-5 feature command failed: {type(exc).__name__}: {exc}"); return 1
if __name__=="__main__": raise SystemExit(main())
