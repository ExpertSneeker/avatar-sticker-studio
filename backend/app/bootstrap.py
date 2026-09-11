"""Create an independent platform administrator; passwords are never defaulted."""
import argparse
import getpass
import json
import secrets
from .auth import DEFAULT_GENERATION_CONCURRENCY, hash_password, public_user
from .db import Database, uid
from .schemas import Signup, PrintSettings


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',required=True)
    parser.add_argument('--username',required=True)
    parser.add_argument('--display-name',required=True)
    parser.add_argument('--generate-password',action='store_true')
    args=parser.parse_args()
    password=secrets.token_urlsafe(24) if args.generate_password else getpass.getpass('New superadmin password: ')
    if not args.generate_password and password!=getpass.getpass('Repeat password: '):
        parser.error('Passwords do not match')
    data=Signup(username=args.username,display_name=args.display_name,password=password)
    db=Database(args.data_dir)
    with db.transaction() as tx:
        if any(u['username'].casefold()==data.username.casefold() for u in tx.all('users')):
            parser.error('Username already exists')
        user=tx.put('users',{'id':uid(),'username':data.username,'display_name':data.display_name,'password':hash_password(data.password),'role':'superadmin','organization_id':None,'organization_name':None,'active':True,'watermark':'','print_defaults':PrintSettings().model_dump(),'generation_concurrency':DEFAULT_GENERATION_CONCURRENCY})
    result={'user':public_user(user)}
    if args.generate_password: result['temporary_password']=password
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
