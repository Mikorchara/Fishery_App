"""M2 entry is disabled; Check never reads an instance/key or starts network."""
import argparse,json
def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args(argv)
 print(json.dumps({'code':'M2_QQ_BOT_DISABLED','network_enabled':False,'ai_enabled':False,'candidate_only':True}))
 return 0
if __name__=='__main__':raise SystemExit(main())
