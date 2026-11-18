from .evidence import at
from .fleet import installed
def cases(db, known_at):
    devices=installed(db,known_at);result=[]
    for row in at(db,'ticket',known_at):
        p=row['payload'];device=devices.get(p['device'])
        if not device:result.append({'ticket':row['id'],'status':'设备待核'});continue
        result.append({'ticket':row['id'],'cohort':device['cohort'],'fault':p['fault'],'part':p['part'],'state':p['state'],'source':row['digest'],'device_source':device['source']})
    return result
