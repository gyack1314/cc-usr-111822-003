from .evidence import at
def installed(db, known_at):
    result={}
    for row in at(db,'device',known_at):
        p=row['payload'];result[row['id']]={'device':row['id'],'cohort':p['cohort'],'model':p['model'],'installed_on':p['installed_on'],'active':p['active'],'source':row['digest']}
    return result
