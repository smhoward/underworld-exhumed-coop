"""Operate isolated UW1 host/client processes through raw keyboard/pointer input.

The native observer only reads world state. No spawning, teleporting, quest/stat
editing or invulnerability is available. The driver and evidence are local files.
"""
import argparse
import collections
import heapq
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/uw1-playthrough'
KEYS=dict(zip('1234567890',[2,3,4,5,6,7,8,9,10,11]))
KEYS.update(dict(zip('qwertyuiop',[16,17,18,19,20,21,22,23,24,25])))
KEYS.update(dict(zip('asdfghjkl',[30,31,32,33,34,35,36,37,38])))
KEYS.update(dict(zip('zxcvbnm',[44,45,46,47,48,49,50])))
KEYS.update(esc=1,enter=28,space=57,shift=42,ctrl=29,alt=56,left=75,right=77,up=72,down=80,backspace=14)
KEYS.update({'.':52,';':39,"'":40,'-':12})
KEYS.update({f'f{i}':58+i for i in range(1,11)})


def state():
    for _ in range(20):
        try:return json.loads((OUT/'host/state.json').read_text())
        except (FileNotFoundError,PermissionError,json.JSONDecodeError):time.sleep(.05)
    raise RuntimeError('Host state unavailable; inspect host.log')


def command(role,op,*args):
    home=OUT/role
    serial=0
    for name in ('ack.txt','command.txt'):
        try:serial=max(serial,int((home/name).read_text().split()[0]))
        except (FileNotFoundError,PermissionError,ValueError,IndexError):pass
    serial+=1
    line=f'{serial} {op} '+ ' '.join(map(str,args))+'\n'
    with (OUT/'inputs.jsonl').open('a') as history:history.write(json.dumps({'time':time.time(),'role':role,'serial':serial,'op':op,'args':args})+'\n')
    temp=home/'command.tmp';temp.write_text(line)
    for _ in range(50):
        try:temp.replace(home/'command.txt');break
        except PermissionError:time.sleep(.01)
    for _ in range(200):
        try:
            if int((home/'ack.txt').read_text())>=serial:return
        except (FileNotFoundError,PermissionError,ValueError):pass
        time.sleep(.01)
    raise RuntimeError(f'{role} did not acknowledge {op}')


def key(role,name,duration=None):
    if duration is None:duration=.25 if name=='j' else .08
    code=KEYS[name];op='key_ext' if name in ('left','right','up','down') else 'key';command(role,op,code,1)
    time.sleep(duration)
    command(role,op,code,0)


def targets(role):
    for _ in range(20):
        try:return json.loads((OUT/'host'/f'targets-{role}.json').read_text())
        except (FileNotFoundError,PermissionError,json.JSONDecodeError):time.sleep(.05)
    raise RuntimeError('Visible targets unavailable')


def mode(role,number):
    for _ in range(5):
        if state()['characters'][role=='client']['interaction']==number:return
        key(role,{1:'f6',2:'f5',3:'f4',4:'f3',5:'f2'}[number],.08);time.sleep(.2)
    raise RuntimeError(f'{role} did not select interaction mode {number}')


def click(role,x,y,duration=.15):
    command(role,'pointer',x,y,0);time.sleep(.05)
    command(role,'pointer',x,y,2);time.sleep(duration);command(role,'pointer',x,y,0);time.sleep(.15)


def snapshot(role):
    """Wait for the native PNG writer, whose input ACK precedes the file write."""
    path=OUT/role/'view.png'
    previous=path.stat().st_mtime_ns if path.exists() else None
    command(role,'shot')
    for _ in range(100):
        try:
            data=path.read_bytes()
            if path.stat().st_mtime_ns!=previous and data.startswith(b'\x89PNG\r\n\x1a\n') and data.endswith(b'\x00\x00\x00\x00IEND\xaeB`\x82'):return data
        except (FileNotFoundError,PermissionError):pass
        time.sleep(.02)
    raise RuntimeError(f'{role} did not finish its native screenshot')


def message_mark():
    path=OUT/'host/messages.jsonl'
    return path.stat().st_size if path.exists() else 0


def messages_since(mark,role=None):
    path=OUT/'host/messages.jsonl'
    if not path.exists():return ''
    with path.open('rb') as source:source.seek(mark);data=source.read()
    texts=[]
    for line in data.splitlines():
        try:
            message=json.loads(line)
            if role is None or message.get('seat')==int(role=='client'):texts.append(message['text'])
        except (ValueError,KeyError,UnicodeDecodeError):pass
    return ''.join(texts)


class InteractionOutOfReach(RuntimeError):pass


def long_jump(role,target=None):
    """Use the modern keys' native standing long jump; observe actual landing."""
    release_movement(role);which=role=='client';before=state()['characters'][which]
    if not before.get('grounded',True):raise RuntimeError('Take off from solid footing')
    trace=[];airborne=False;braked=False;began=time.monotonic()
    try:
        command(role,'key',KEYS['ctrl'],1);command(role,'key',KEYS['shift'],1);time.sleep(.2)
        command(role,'key',KEYS['shift'],0);command(role,'key',KEYS['ctrl'],0)
        command(role,'key',KEYS['w'],1)
        while time.monotonic()-began<4:
            time.sleep(.05);current=state()['characters'][which];trace.append(current)
            airborne=airborne or not current.get('grounded',True)
            if target and airborne and not braked and max(abs(current['x']/256-target[0]),abs(current['y']/256-target[1]))<.35:
                command(role,'key',KEYS['w'],0);braked=True
            if airborne and current.get('grounded',True):return current
        raise RuntimeError('The native long jump did not take off and land')
    finally:
        release_movement(role)
        (OUT/f'last-jump-{role}.json').write_text(json.dumps({'before':before,'target':target,'braked':braked,'trace':trace},indent=2))


def fly(role,x,y,z=None,timeout=30):
    """Fly with an existing native spell or potion using modern Shift/Ctrl keys."""
    which=role=='client';began=time.monotonic();release_movement(role)
    try:
        command(role,'pointer',230,150,0)
        if not state()['characters'][which].get('motion_effects',0)&16:
            raise RuntimeError('Use a genuine flight effect first')
        if z is not None:
            for _ in range(30):
                current=state()['characters'][which];delta=z-current['z']/64
                if abs(delta)<.15:break
                if not current['motion_effects']&16:raise RuntimeError('Original flight effect expired')
                key(role,'shift' if delta>0 else 'ctrl',min(.15,max(.05,abs(delta)/10)));time.sleep(.1)
            else:raise RuntimeError('Original terrain prevents the requested flight height')
        while time.monotonic()-began<timeout:
            current=state()['characters'][which];dx=x-current['x']/256;dy=y-current['y']/256
            if not current['motion_effects']&16:raise RuntimeError('Original flight effect expired')
            if z is not None and current['z']/64<z-1:raise RuntimeError('Fell below the intended flight height')
            if max(abs(dx),abs(dy))<.18:
                print(f'{role} flew to {x},{y} at height {current["z"]/64:.2f}',flush=True);return
            face(role,math.degrees(math.atan2(dx,dy)))
            distance=math.hypot(dx,dy)
            key(role,'w' if distance>.6 else 'x',min(.3,max(.05,distance/4)));time.sleep(.1)
        raise RuntimeError('Flight did not reach the original destination')
    finally:release_movement(role)


def quantity(role,count):
    # UW1 waits for the mouse button to come up before reading the number.
    # Typing while still holding it can select the native right-click "all" shortcut.
    command(role,'pointer',160,100,0);time.sleep(.2)
    for _ in range(3):key(role,'backspace')
    for digit in str(count):key(role,digit)
    key(role,'enter');time.sleep(.2)


def carried_count(s,which,item):
    objects={o['index']:o for o in s['objects']};seen=set()
    def visit(index):
        if not index or index in seen or index not in objects:return 0
        seen.add(index);o=objects[index]
        total=(o['link'] if o['quantity'] and not o['link']&512 else 1) if o['item']==item else 0
        child=o['link'] if not o['quantity'] and 128<=o['item']<144 else 0
        while child and child in objects:
            if child in seen:break
            total+=visit(child);child=objects[child]['next']
        return total
    return sum(visit(n) for n in s['characters'][which]['inventory'][:19])


def place_cursor(role,slot):
    s=state();which=role=='client';index=s['characters'][which]['cursor']
    if not index:return
    if s['characters'][which]['input_mode']==2:raise RuntimeError('Complete the native two-object use before placing its cursor')
    obj=next(o for o in s['objects'] if o['index']==index)
    expected=carried_count(s,which,obj['item'])+(obj['link'] if obj['quantity'] and not obj['link']&512 else 1)
    for _ in range(3):
        command(role,'pointer',*slot_point(slot),1);time.sleep(.1);command(role,'pointer',*slot_point(slot),0)
        for _ in range(20):
            s=state()
            if not s['characters'][which]['cursor'] and carried_count(s,which,obj['item'])==expected:return
            time.sleep(.1)
    raise RuntimeError('The native inventory did not accept the held object')


def interact(role,index,action='use',destination=None):
    current=state();which=role=='client'
    if action=='get' and current['characters'][which]['cursor']:
        raise RuntimeError('Put the held object in an inventory slot before picking up another object')
    mode(role,{'use':1,'fight':2,'look':3,'get':4,'talk':5}[action])
    obj=next((o for o in state()['objects'] if o['index']==index),None)
    found=next((t for t in targets(role) if t['index']==index),None)
    if not found:raise RuntimeError(f'Object {index} is outside {role} view')
    before=carried_count(state(),which,obj['item']) if action=='get' and destination else None
    mark=message_mark()
    if destination:
        command(role,'pointer',found['x'],found['y'],2);time.sleep(.6)
        if action=='get' and obj and obj['quantity'] and obj['link']>1 and state()['story']:
            quantity(role,obj['link'])
        command(role,'pointer',*destination,2);time.sleep(.35)
        command(role,'pointer',*destination,0);time.sleep(.25)
        if state()['characters'][role=='client']['cursor']:
            click(role,*destination)
        if action=='get':
            expected=before+(obj['link'] if obj['quantity'] and not obj['link']&512 else 1)
            for _ in range(40):
                received=state()
                if not received['characters'][which]['cursor'] and carried_count(received,which,obj['item'])==expected:break
                time.sleep(.1)
            else:raise RuntimeError('Native pickup did not add the item; inspect its range and destination')
    else:click(role,found['x'],found['y'])
    if any(text in messages_since(mark,role).lower() for text in ('cannot reach','unable to use that from here')):
        raise InteractionOutOfReach('The original interaction was out of reach; move closer before continuing')


def checkpoint(label):
    current=state()
    if current['screen']!=0 or current['story'] or current['modal']>=0:
        raise RuntimeError('Close the native dialog before requesting a campaign checkpoint')
    before=inventory_signature(current)
    command('host','save');time.sleep(.25);key('host','enter');time.sleep(1)
    for _ in range(100):
        latest=state()
        if latest['frame']>current['frame'] and not latest['story'] and latest['modal']<0 and inventory_signature(latest)==before:break
        time.sleep(.1)
    else:raise RuntimeError('Native save did not resume with a fresh matching inventory snapshot')
    import shutil
    destination=OUT/'evidence'/label;destination.mkdir(parents=True,exist_ok=True)
    shutil.copytree(OUT/'host/SAVE1',destination/'SAVE1',dirs_exist_ok=True)
    (destination/'state.json').write_text(json.dumps(state()))
    for role in ('host','client'):
        (destination/(role+'.png')).write_bytes(snapshot(role))
        shutil.copy(OUT/(role+'.log'),destination/(role+'.log'))


def restore(slot=1):
    """Restore through the host's original Ctrl+R menu."""
    if not 1<=slot<=4:raise ValueError('Native save slots are 1 to 4')
    before=state()
    if before['screen']!=0 or before['story'] or before['modal']>=0:
        raise RuntimeError('Close the native dialog before restoring')
    log=OUT/'host.log';offset=log.stat().st_size
    command('host','key',KEYS['ctrl'],1)
    try:key('host','r')
    finally:command('host','key',KEYS['ctrl'],0)
    click('host',20,34+15*(slot-1))
    for _ in range(100):
        current=state()
        with log.open('rb') as stream:
            stream.seek(offset);restored=b'independent character restored' in stream.read()
        if restored and current['frame']>before['frame'] and not current['story'] and current['modal']<0:return
        time.sleep(.1)
    raise RuntimeError('Native restore did not resume gameplay')


def inventory_signature(s):
    objects={o['index']:o for o in s['objects']}
    def item(index,seen):
        if not index:return None
        if index in seen:raise RuntimeError('Cycle in inventory graph')
        seen=seen|{index};o=objects[index]
        contents=[];child=o['link'] if not o['quantity'] and 0x80<=o['item']<=0x8f else 0
        while child:
            contents.append(item(child,seen));child=objects[child]['next']
        return o['item']&~1 if 0x80<=o['item']<0x8c else o['item'],o['hp'],o['link'] if o['quantity'] else 1,contents
    return [[item(n,set()) for n in c['inventory'][:19]]+[item(c['cursor'],set())] for c in s['characters']]


def slot_point(slot):
    if slot==19:return 248,70
    if 20<=slot<=27:slot-=9
    if 11<=slot<=18:return 248+19*((slot-11)%4),89+18*((slot-11)//4)
    return {0:(277,17),1:(277,34),2:(277,49),3:(277,63),4:(277,76),
            5:(252,20),6:(301,20),7:(250,46),8:(304,46),9:(253,58),10:(300,60)}[slot]


def inventory_drag(role,index,destination):
    mode(role,4);before=state();inv=before['characters'][role=='client']['inventory'];slot=inv.index(index)
    signature=inventory_signature(before)[role=='client']
    command(role,'pointer',*slot_point(slot),0);time.sleep(.05)
    command(role,'pointer',*slot_point(slot),2);time.sleep(.6)
    command(role,'pointer',*destination,2);time.sleep(.35)
    command(role,'pointer',*destination,0);time.sleep(.25)
    if destination[0]>=238:
        for _ in range(30):
            current=state()
            if current['story']:break
            if not current['characters'][role=='client']['cursor']:
                if inventory_signature(current)[role=='client']==signature:
                    raise RuntimeError('Native inventory did not change; verify the inventory panel is visible before dragging')
                break
            time.sleep(.1)
        else:raise RuntimeError('Native inventory destination rejected the item; place the held cursor item before continuing')


def closed_door(s,tile):
    pos=positions(s)
    return next((o for o in s['objects']
                 if pos.get(o['index'])==tile and 0x140<=o['item']<0x148),None)


def unlock(role,index):
    """Try carried, visible keys through the native two-object Use action."""
    s=state();which=role=='client';tile=positions(s)[index]
    objects={o['index']:o for o in s['objects']}
    slots=[i for i,n in enumerate(s['characters'][which]['inventory'])
           if n and n in objects and 0x101<=objects[n]['item']<0x10f]
    for slot in slots:
        door=closed_door(state(),tile)
        if door is None:return True
        if not any(t['index']==door['index'] for t in targets(role)):
            raise RuntimeError('Face the closed door before selecting a key')
        mode(role,1);click(role,*slot_point(slot))
        if state()['characters'][which]['input_mode']!=2:
            raise RuntimeError('The native key did not enter target mode')
        mark=message_mark();interact(role,door['index']);time.sleep(.2)
        if any(text in messages_since(mark,role).lower() for text in ('cannot reach','unable to use that from here')):
            raise InteractionOutOfReach('Move closer before trying the carried keys')
        if state()['characters'][which]['input_mode']==2:
            raise RuntimeError('The native key target is still pending')
        door=closed_door(state(),tile)
        if door is None:return True
        interact(role,door['index'])
        for _ in range(20):
            if closed_door(state(),tile) is None:return True
            time.sleep(.1)
    return False


def barter_offer(role,index,count=None,slot=0):
    s=state()
    if s['screen']!=2:raise RuntimeError('A native conversation must be open before offering an item')
    if s['story']:raise RuntimeError('Finish the native text prompt before offering an item')
    inv=s['characters'][role=='client']['inventory'];x,y=slot_point(inv.index(index))
    obj=next(o for o in s['objects'] if o['index']==index)
    units=(count if count is not None else obj['link']) if obj['quantity'] and 1<obj['link']<512 else 1
    expected=carried_count(s,role=='client',obj['item'])-units
    command(role,'pointer',x,y,0);time.sleep(.1)
    command(role,'pointer',x,y,2);time.sleep(.2)
    command(role,'pointer',x-10,y,2);time.sleep(.4)  # native drag threshold is six pixels
    # Native screen coordinates invert the DOS bottom-origin slot table.
    trade_x,trade_y=154+21*(slot%2),20+18*(slot//2)
    if obj['quantity'] and 1<obj['link']<512:
        if not state()['story']:raise RuntimeError('The native quantity prompt did not open')
        quantity(role,count if count is not None else obj['link'])
    else:
        command(role,'pointer',trade_x,trade_y,2);time.sleep(.2)
        command(role,'pointer',trade_x,trade_y,0);time.sleep(.2)
    for _ in range(3):
        current=state()
        if not current['characters'][role=='client']['cursor'] and carried_count(current,role=='client',obj['item'])==expected:return
        command(role,'pointer',trade_x,trade_y,0);time.sleep(.2)
        click(role,trade_x,trade_y,.2)
        for _ in range(10):
            current=state()
            if not current['characters'][role=='client']['cursor'] and carried_count(current,role=='client',obj['item'])==expected:return
            time.sleep(.1)
    raise RuntimeError('The native trade slot did not accept the held offer')


def dialogue(role,choices=()):
    pending=iter(choices)
    for _ in range(100):
        s=state()
        if s['screen']!=2:return []
        menu=s.get('menu',[])
        if menu:
            try:wanted=next(pending)
            except StopIteration:return menu
            if isinstance(wanted,int):number=wanted
            else:
                matches=[i+1 for i,t in enumerate(menu) if wanted.lower() in t.lower()]
                if len(matches)!=1:raise RuntimeError(f'Choice {wanted!r} is ambiguous or absent: {menu}')
                number=matches[0]
            print('Dialogue:',menu[number-1],flush=True);key(role,str(number));time.sleep(.4)
        else:key(role,'space');time.sleep(.15)
    raise RuntimeError('Conversation did not reach a menu or finish')


def face_object(role,index):
    s=state();x,y=object_point(s,index);c=s['characters'][role=='client']
    face(role,math.degrees(math.atan2(x-c['x']/256,y-c['y']/256)))


def object_point(s,index):
    x,y=positions(s)[index];obj=next(o for o in s['objects'] if o['index']==index)
    pos=obj.get('position')
    return (x+((pos>>13)&7)/8,y+((pos>>10)&7)/8) if pos is not None and not 320<=obj['item']<336 else (x+.5,y+.5)


def strike(role,style=';',charge=100):
    """Charge and complete one actual native swing, including its recovery."""
    which=role=='client';code=KEYS[style];before=state()['characters'][which]
    command(role,'key',code,1)
    try:
        began=time.monotonic()
        while time.monotonic()-began<3:
            current=state()['characters'][which];attack=current['attack']
            if current['motion_state']&1 or current['xp']<before['xp'] or not current['drawn']:return False
            if attack[0]<0 and attack[1]==3 and attack[2]>=charge:break
            time.sleep(.05)
        else:raise RuntimeError('Native attack did not reach its requested charge')
    finally:command(role,'key',code,0)
    began=time.monotonic()
    while time.monotonic()-began<3:
        if state()['characters'][which]['attack'][0]==0:return True
        time.sleep(.05)
    raise RuntimeError('Native attack did not complete recovery')


def talk(role,name,choices=()):
    for _ in range(8):
        s=state();npc=next(o for o in s['objects'] if o['index']==name) if isinstance(name,int) else next(o for o in s['objects'] if o['npc_name'].lower()==name.lower());index=npc['index']
        mode(role,5);face_object(role,index);time.sleep(.15)
        found=next((t for t in targets(role) if t['index']==index),None)
        if found:
            click(role,found['x'],found['y']);time.sleep(.2)
            if state()['screen']==2:return dialogue(role,choices)
        # A visible NPC can still be beyond the original speaking reach.
        # Approach after a rejected click rather than repeatedly clicking it.
        s=state();px,py=positions(s)[index];c=s['characters'][role=='client'];start=(c['x']//256,c['y']//256)
        other=s['characters'][role!='client'];blocked=(other['x']//256,other['y']//256);possible=[]
        for x,y in ((px-1,py),(px+1,py),(px,py-1),(px,py+1)):
            try:possible.append((len(path(s,start,(x,y),blocked,True,1,start_height=c['z']/64)),x,y))
            except RuntimeError:pass
        if not possible:raise RuntimeError(f'No reachable position next to {name}')
        _,x,y=min(possible);go(role,x,y)
    raise RuntimeError(f'{name} did not start a conversation')


def melee_style(s,which,enemy):
    c=s['characters'][which];avatar=next(o for o in s['objects'] if o['index']==c['index'])
    for style,third in ((';',2),('.',1),('p',3)):
        plane=int(c['z']/8)+avatar['height']*third//3
        if enemy['z']<=plane<enemy['z']+enemy['height']:return style
    return None


def clear_melee_line(s,which,enemy):
    c=s['characters'][which];px,py=c['x']/256,c['y']/256;ex,ey=object_point(s,enemy['index'])
    pos=positions(s);doors={pos[o['index']] for o in s['objects'] if 320<=o['item']<328 and o['index'] in pos}
    steps=max(1,math.ceil(math.hypot(ex-px,ey-py)*16))
    for step in range(1,steps):
        x=px+(ex-px)*step/steps;y=py+(ey-py)*step/steps;cell=(int(x),int(y));tile=s['tiles'][cell[0]+cell[1]*64]
        fx,fy=int(x*8)&7,int(y*8)&7
        if tile[0]==0 or cell in doors:return False
        if ((tile[0]==2 and fy>=fx) or (tile[0]==3 and fx+fy>=7)
            or (tile[0]==4 and fx+fy<=7) or (tile[0]==5 and fy<=fx)):return False
    return True


def fight(role,index,timeout=180):
    if state()['characters'][role=='client']['motion_state']&1:return False
    release_movement(role);mode(role,2);key(role,'2');time.sleep(.6);began=time.monotonic()
    while time.monotonic()-began<timeout:
        s=state();enemy=next((o for o in s['objects'] if o['index']==index and 0x40<=o['item']<0x7f),None)
        if not enemy or enemy['hp']==0:return True
        style=melee_style(s,role=='client',enemy)
        if style is None or not clear_melee_line(s,role=='client',enemy):return False
        c=s['characters'][role=='client'];ex,ey=object_point(s,index);distance=math.hypot(ex-c['x']/256,ey-c['y']/256)
        if distance>3:return False  # A native rescue can move the player to the companion.
        face_object(role,index)
        if distance>.70:
            key(role,'w',min(.3,max(.08,(distance-.6)/3)));time.sleep(.12);continue
        if not strike(role,style):return False
        if state()['screen']!=0:return False
    raise RuntimeError(f'Combat with {index} did not finish')


def positions(s):
    result={};objects={o['index']:o for o in s['objects']}
    for tile,t in enumerate(s['tiles']):
        index=t[4];seen=set()
        while index and index not in seen and index in objects:
            seen.add(index);result[index]=(tile%64,tile//64);index=objects[index]['next']
    return result


def level_exits(s):
    """Original movement triggers leading to another shared game level."""
    objects={o['index']:o for o in s['objects']};pos=positions(s);exits={}
    for o in s['objects']:
        if o['item'] not in (416,420) or o['index'] not in pos:continue
        link=o['link'];seen=set()
        while link in objects and link not in seen:
            seen.add(link);trap=objects[link]
            if trap['item']==385 and trap['z'] not in (0,s['level']):
                exits[pos[o['index']]]=trap['z'];break
            link=trap['link']
    return exits


def summary():
    s=state();pos=positions(s)
    print(json.dumps({k:s[k] for k in ('frame','level','screen','modal','story','characters')},indent=2))
    for o in s['objects']:
        if o.get('npc_name') or o.get('fate')==10 or o['item'] in (0x118,0x119,0x120,0x121,0x122,0x123,0x124,0x125,0x12a):
            print(o['index'],hex(o['item']),pos.get(o['index']),o['npc_name'] or o['name'],'hp',o['hp'],'goal',o['goal'])


def world_surfaces(s):
    surfaces={i:[tuple(t[:3])] for i,t in enumerate(s['tiles'])}
    pos=positions(s)
    for o in s['objects']:
        if o['name']=='a_bridge' and o['index'] in pos:
            x,y=pos[o['index']];surfaces[x+y*64].append((1,(o['z']+o['height'])/8,0))
    return surfaces


def surface_height(surface,direction=None):
    rise={6:(0,1),7:(0,-1),8:(1,0),9:(-1,0)}.get(surface[0])
    if rise is None:return surface[1]
    return surface[1]+(1 if direction==rise else 0 if direction==(-rise[0],-rise[1]) else .5)


def path(s,start,target,blocked=None,diagonals=False,max_rise=1,*,start_height=None,layered=False,jumping=False,avoid=(),max_drop=1.25,water_cost=30):
    tiles=s['tiles'];surfaces=world_surfaces(s)
    if not tiles[target[0]+target[1]*64][0]:raise RuntimeError(f'Target {target} is a wall, not a walking destination')
    choices=surfaces[start[0]+start[1]*64]
    if start_height is None:start_height=surface_height(choices[0])
    initial=(*start,min(range(len(choices)),key=lambda i:abs(surface_height(choices[i])-start_height)))
    queue=[(0,initial)];previous={initial:None};costs={initial:0}
    pos=positions(s)
    obstacles={pos[o['index']] for o in s['objects'] if o['index']>=256 and o['index'] in pos and o.get('height',0)>8 and o.get('radius',0)>=2 and not (0x140<=o['item']<0x150 or 0x180<=o['item']<0x1c0)}
    obstacles.update(pos[o['index']] for o in s['objects'] if o['name']=='a_pillar'
                     and o['index'] in pos and pos[o['index']] not in (start,target))
    obstacles.update(tile for tile in level_exits(s) if tile not in (start,target))
    obstacles.update(avoid)
    edges={2:{(1,0),(0,-1)},3:{(-1,0),(0,-1)},4:{(1,0),(0,1)},5:{(-1,0),(0,1)}}
    while queue:
        cost,at=heapq.heappop(queue)
        if cost!=costs[at]:continue
        if at[:2]==target:
            result=[]
            while previous[at] is not None:result.append(at);at=previous[at]
            return [cell if layered else cell[:2] for cell in result[::-1]]
        x,y,layer=at
        if jumping:
            source=surfaces[x+y*64][layer]
            for dx,dy in ((-1,0),(1,0),(0,-1),(0,1)):
                mx,my=x+dx,y+dy;nx,ny=x+2*dx,y+2*dy
                if not (1<=nx<63 and 1<=ny<63) or (nx,ny) in obstacles:continue
                gap=surfaces[mx+my*64][0]
                if source[0]!=1 or source[2] or gap[0]!=1 or gap[1]>=source[1]-2:continue
                for nextlayer,landing in enumerate(surfaces[nx+ny*64]):
                    if landing[0]!=1 or landing[2] or abs(landing[1]-source[1])>1:continue
                    node=(nx,ny,nextlayer);candidate=cost+10
                    if candidate<costs.get(node,float('inf')):
                        costs[node]=candidate;previous[node]=at;heapq.heappush(queue,(candidate,node))
        for nx,ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            nxt=(nx,ny)
            if not (1<=nx<63 and 1<=ny<63):continue
            if nxt in obstacles:continue
            a=tiles[x+y*64];b=tiles[nx+ny*64]
            direction=(nx-x,ny-y)
            if a[0] in edges and direction not in edges[a[0]]:continue
            if b[0] in edges and (-direction[0],-direction[1]) not in edges[b[0]]:continue
            if b[0]==0:continue
            if not diagonals and 2<=b[0]<=5:continue
            for nextlayer,bs in enumerate(surfaces[nx+ny*64]):
                asurface=surfaces[x+y*64][layer]
                # A character can stand over a low tile while its body still
                # rests on the adjacent ledge. Start from the observed footing
                # height so walking back onto that ledge remains reachable.
                source_height=start_height if at==initial else surface_height(asurface,direction)
                rise=surface_height(bs,(-direction[0],-direction[1]))-source_height
                if bs[2]==2 or rise>max_rise:continue
                if max_drop is not None and rise < -max_drop:continue
                if nextlayer==0 and len(surfaces[nx+ny*64])>1 and surface_height(bs)+23/8>surfaces[nx+ny*64][1][1]-.25:continue
                node=(nx,ny,nextlayer)
                candidate=cost+1+(water_cost if bs[2]==1 else 0)+(4 if rise>1 else 0)+(2 if 2<=b[0]<=5 else 0)
                if candidate<costs.get(node,float('inf')):
                    costs[node]=candidate;previous[node]=at;heapq.heappush(queue,(candidate,node))
    raise RuntimeError(f'No walking route from {start} to {target}')


def go(role,x,y,engage=False,jumping=False,max_rise=1,*,water_cost=30,max_drop=1.25):
    if state()['characters'][role=='client']['cursor']:
        raise RuntimeError('Place the held cursor item before starting a walking route')
    release_movement(role)
    which=role=='client';held=None;began=time.monotonic();last=None;stalled=0;waypoint=None;jumped_for=None;avoid=set();ignored_enemies=set();combat_cell=None
    original_level=state()['level']
    try:
        while time.monotonic()-began<600:
            s=state();c=s['characters'][which]
            if s['level']!=original_level:
                print(f'{role} travelled from level {original_level} to {s["level"]}',flush=True)
                return
            if s['screen']!=0 or s['story']:raise RuntimeError('Navigation interrupted by a modal screen')
            px,py=c['x']/256,c['y']/256;start=(int(px),int(py))
            if start!=combat_cell:ignored_enemies.clear();combat_cell=start
            party_indices={member['index'] for member in s['characters']}
            threats=[o for o in s['objects'] if 0x40<=o['item']<0x7f and o['hp']
                     and o['index'] not in ignored_enemies
                     and ((o['goal'] in (4,5,6,9) and o.get('attitude')==0)
                          or (o['goal'] in (5,9) and o.get('target') in party_indices))
                     and abs(o['z']/8-c['z']/64)<3
                     and melee_style(s,which,o) is not None
                     and clear_melee_line(s,which,o)
                     and math.hypot(o['x']+.5-px,o['y']+.5-py)<2.5]
            if engage and threats and not c['motion_state']&1 and s['tiles'][start[0]+start[1]*64][2]!=1:
                if held:command(role,'key',KEYS[held],0);held=None
                target_enemy=min(threats,key=lambda o:math.hypot(o['x']+.5-px,o['y']+.5-py))['index']
                defeated=fight(role,target_enemy)
                if not defeated:ignored_enemies.add(target_enemy)
                after=state()
                if not defeated and after['screen']!=0:
                    raise RuntimeError('Combat interrupted by a native modal screen')
                if after['characters'][which]['xp']<c['xp']:
                    print(f'{role}: native companion revival; replanning from the restored position',flush=True)
                waypoint=None;continue
            other=s['characters'][1-which]
            def point(cell):
                offsets={2:(.875,.3125),3:(.1875,.1875),4:(.8125,.8125),5:(.3125,.875)}
                ox,oy=offsets.get(s['tiles'][cell[0]+cell[1]*64][0],(.5,.5))
                objects={o['index']:o for o in s['objects']};idx=s['tiles'][cell[0]+cell[1]*64][4];seen=set()
                while idx and idx in objects and idx not in seen:
                    seen.add(idx);o=objects[idx]
                    if o['name']=='a_pillar':ox,oy=.875,.875
                    idx=o['next']
                return cell[0]+ox,cell[1]+oy
            def tolerance(cell):return .08 if point(cell)==(cell[0]+.875,cell[1]+.875) else .18
            surfaces=world_surfaces(s)
            def height(cell):return surface_height(surfaces[cell[0]+cell[1]*64][cell[2]])
            # Native co-op revival can move a character beside the companion.
            # Discard the old local waypoint before giving further movement.
            if waypoint and max(abs(waypoint[0]+.5-px),abs(waypoint[1]+.5-py))>3:
                waypoint=None
            wx,wy=point(waypoint) if waypoint else (0,0)
            start_point=point(start)
            if waypoint is None or (max(abs(wx-px),abs(wy-py))<tolerance(waypoint) and abs(height(waypoint)-c['z']/64)<.5):
                route=path(s,start,(x,y),(other['x']//256,other['y']//256),True,max_rise,start_height=c['z']/64,layered=True,jumping=jumping,avoid=avoid,water_cost=water_cost,max_drop=max_drop)
                currentlayer=min(range(len(surfaces[x+y*64])),key=lambda i:abs(surface_height(surfaces[x+y*64][i])-c['z']/64))
                waypoint=route[0] if route else (x,y,currentlayer)
            target=waypoint
            tx,ty=point(target);dx,dy=tx-px,ty-py
            # Leave a pillar tile along its clear outer edge. Steering directly
            # toward the next tile centre cuts through the pillar's footprint.
            if start_point==(start[0]+.875,start[1]+.875) and target[:2]!=start:
                if held:command(role,'key',KEYS[held],0);held=None
                if target[0]!=start[0]:
                    edge=start[1]+(.875 if py-start[1]>=.5 else -.125)
                    aligning=abs(edge-py)>.04
                    direction=(0 if edge>py else 180) if aligning else (90 if target[0]>start[0] else 270)
                    duration=min(.08,max(.02,abs(edge-py)/2.5)) if aligning else .15
                else:
                    edge=start[0]+(.875 if px-start[0]>=.5 else -.125)
                    aligning=abs(edge-px)>.04
                    direction=(90 if edge>px else 270) if aligning else (0 if target[1]>start[1] else 180)
                    duration=min(.08,max(.02,abs(edge-px)/2.5)) if aligning else .15
                face(role,direction);key(role,'x',duration);continue
            if jumping and max(abs(target[0]-start[0]),abs(target[1]-start[1]))==2 and jumped_for!=target:
                if closed_door(s,target[:2]):
                    raise RuntimeError(f'Open the landing door at {target[:2]} before jumping')
                object_tiles=positions(s)
                if any(o['item']==0x14d and object_tiles.get(o['index'])==target[:2]
                       and o['z']/8-height(target)<23/8+2.5 for o in s['objects']):
                    raise RuntimeError('The raised stone door needs an earlier native takeoff to clear its underside')
                release_movement(role);held=None
                face(role,math.degrees(math.atan2(dx,dy)))
                # Observe takeoff before braking near the destination. A lower
                # landing platform gives a longer flight than an ascending one.
                landing=long_jump(role,(tx,ty));held=None;jumped_for=target
                if landing['z']/64<height(target)-1:
                    raise RuntimeError(f'Native jump landed below {target}; recover before retrying')
                continue
            if jumped_for==target and not c.get('grounded',True):
                # Input acknowledgement precedes simulation. Keep the original
                # takeoff movement until landing, rather than slowing in midair
                # using a stale pre-jump snapshot or a nearby waypoint.
                time.sleep(.1);continue
            if 2<=s['tiles'][target[0]+target[1]*64][0]<=5 and start!=target[:2]:
                if start[1]==target[1] and abs(dy)>.10:
                    if held:command(role,'key',KEYS[held],0);held=None
                    face(role,0 if dy>0 else 180);key(role,'x',min(.25,abs(dy)/1.5));continue
                if start[0]==target[0] and abs(dx)>.10:
                    if held:command(role,'key',KEYS[held],0);held=None
                    face(role,90 if dx>0 else 270);key(role,'x',min(.25,abs(dx)/1.5));continue
            door=closed_door(s,target[:2]) or (closed_door(s,start) if stalled>2 else None)
            if door and c.get('grounded',True) and max(abs(dx),abs(dy))<1.1:
                door_tile=positions(s)[door['index']]
                if held:command(role,'key',KEYS[held],0);held=None
                face_object(role,door['index']);mark=message_mark();interact(role,door['index']);time.sleep(.5)
                if any(text in messages_since(mark,role).lower() for text in ('cannot reach','unable to use that from here')):
                    key(role,'x',.15);continue
                changed=closed_door(state(),door_tile)
                try:locked=changed and not unlock(role,changed['index'])
                except InteractionOutOfReach:
                    key(role,'x',.15);continue
                if locked:
                    print(f'{role}: locked door at {door_tile}; looking for another route',flush=True)
                    avoid.add(door_tile);waypoint=None
                continue
            if target[:2]==(x,y) and max(abs(dx),abs(dy))<tolerance(target) and abs(height(target)-c['z']/64)<.5:break
            drop=height(target)-c['z']/64<-1
            if drop and jumped_for!=target:
                if held:command(role,'key',KEYS[held],0);held=None
                face(role,math.degrees(math.atan2(dx,dy)));jumped_for=target;continue
            angle=c['facing']*math.tau/65536
            forward=dy*math.cos(angle)+dx*math.sin(angle)
            right=dx*math.cos(angle)-dy*math.sin(angle)
            wet=bool(c.get('terrain',2 if s['tiles'][start[0]+start[1]*64][2]==1 else 1)&(2|32))
            if (wet or (drop and c.get('grounded',True))) and (abs(right)>abs(forward)*.35 or forward<0):
                if held:command(role,'key',KEYS[held],0);held=None
                face(role,math.degrees(math.atan2(dx,dy)));continue
            sideways=abs(right)>abs(forward)
            if stalled>3:sideways=not sideways
            wanted='w' if wet else ('d' if right>0 else 'a') if sideways else (('w' if drop else 'x') if forward>0 else 's')
            if jumped_for==target and not c.get('grounded',True) and forward>.25 and abs(right)<.3:wanted='w'
            if wanted!=held:
                if held:command(role,'key',KEYS[held],0)
                command(role,'key',KEYS[wanted],1);held=wanted
            if jumped_for!=target and height(target)-c['z']/64>1:
                key(role,'j');jumped_for=target
            current=(c['x'],c['y'])
            stalled=stalled+1 if current==last else 0;last=current
            if stalled>25:raise RuntimeError(f'Blocked at {px:.2f},{py:.2f} toward {target}')
            time.sleep(.10)
        else:raise RuntimeError('Walking deadline exceeded')
    finally:
        if held:command(role,'key',KEYS[held],0)
        time.sleep(.5)
    print(f'{role} reached {x},{y} on level {state()["level"]}')


def face(role,degrees):
    which=role=='client';desired=round(degrees*65536/360)%65536
    for _ in range(15):
        current=state()['characters'][which]['facing'];delta=(desired-current+32768)%65536-32768
        if abs(delta)<1100:return
        key(role,'right' if delta>0 else 'left',max(.035,min(.25,abs(delta)/45000)))
        time.sleep(.14)
    raise RuntimeError('Facing did not settle')


def release_movement(role):
    for name in ('w','x','a','d','s','ctrl','shift'):command(role,'key',KEYS[name],0)
    for name in ('left','right','up','down'):command(role,'key_ext',KEYS[name],0)
    time.sleep(.2)


def run(data,duration,resume=False,chargen=False,binary=None):
    binary=(binary or ROOT/'build/coop-windows/bin/uw1/uw1port.exe').resolve()
    with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    processes=[];files=[]
    try:
        for role in ('host','client'):
            home=OUT/role;home.mkdir(parents=True,exist_ok=True)
            for name in ('command.txt','ack.txt','state.json'):(home/name).unlink(missing_ok=True)
            env=dict(os.environ,UW_COOP_TEST_START='1',UW_COOP_TEST_TRACE='1',UW_COOP_TEST_CAMPAIGN='playthrough',UW_COOP_BOT_HOME=str(home))
            if resume:env['UW_COOP_TEST_RESUME']=str(resume)
            if chargen:env.update(UW_COOP_BOT_CHARGEN='1',UW_COOP_TEST_CHARGEN='1')
            env['PATH']=str(binary.parent)+os.pathsep+str(ROOT/'build/toolchain/msys64/clang64/bin')+os.pathsep+os.environ['WINDIR']+'\\System32'+os.pathsep+os.environ['WINDIR']
            log=(OUT/(role+'.log')).open('w');files.append(log)
            cmd=[str(binary),'--coop-shared','--hidden','--no-recording','--home',str(home),'--no-audio','--exit-after',str(duration*1000),'--screenshot-after','30000','--screenshot',str(OUT/(role+'.png'))]
            cmd+=['--data',str(data),'--coop-host',str(port),'--enhance','skip-intro,modern-keys'] if role=='host' else ['--coop-join',f'127.0.0.1:{port}']
            processes.append(subprocess.Popen(cmd,env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT))
        (OUT/'session.json').write_text(json.dumps({'pids':[p.pid for p in processes],'port':port,'binary':str(binary),'started':time.time()}))
        print('Isolated UW1 co-op campaign is running; use state/key/pointer/go commands.',flush=True)
        while all(p.poll() is None for p in processes):time.sleep(1)
        print('Game process ended:',[p.poll() for p in processes],flush=True)
    finally:
        for p in processes:
            if p.poll() is None:p.kill();p.wait()
        for f in files:f.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('run');p.add_argument('--data',type=Path,required=True);p.add_argument('--duration',type=int,default=3600);p.add_argument('--resume',type=int,choices=range(1,5));p.add_argument('--chargen',action='store_true');p.add_argument('--binary',type=Path)
    sub.add_parser('state')
    p=sub.add_parser('key');p.add_argument('role',choices=['host','client']);p.add_argument('name',choices=sorted(KEYS));p.add_argument('--duration',type=float)
    p=sub.add_parser('pointer');p.add_argument('role',choices=['host','client']);p.add_argument('x',type=int);p.add_argument('y',type=int);p.add_argument('buttons',type=int,nargs='?',default=0)
    p=sub.add_parser('shot');p.add_argument('role',choices=['host','client'])
    p=sub.add_parser('jump');p.add_argument('role',choices=['host','client'])
    p=sub.add_parser('fly');p.add_argument('role',choices=['host','client']);p.add_argument('x',type=float);p.add_argument('y',type=float);p.add_argument('--height',type=float)
    sub.add_parser('save')
    p=sub.add_parser('restore');p.add_argument('--slot',type=int,choices=range(1,5),default=1)
    p=sub.add_parser('go');p.add_argument('role',choices=['host','client']);p.add_argument('x',type=int);p.add_argument('y',type=int)
    p.add_argument('--engage',action='store_true');p.add_argument('--jumping',action='store_true')
    p.add_argument('--max-drop',type=float,default=1.25,help='Largest planned downward step in original tile-height units; native collision and fall damage still apply')
    p=sub.add_parser('face');p.add_argument('role',choices=['host','client']);p.add_argument('degrees',type=float)
    args=parser.parse_args()
    if args.action=='run':run(args.data,args.duration,args.resume,args.chargen,args.binary)
    elif args.action=='state':summary()
    elif args.action=='key':key(args.role,args.name,args.duration)
    elif args.action=='pointer':command(args.role,'pointer',args.x,args.y,args.buttons)
    elif args.action=='shot':snapshot(args.role)
    elif args.action=='jump':long_jump(args.role)
    elif args.action=='fly':fly(args.role,args.x,args.y,args.height)
    elif args.action=='save':command('host','save')
    elif args.action=='restore':restore(args.slot)
    elif args.action=='go':go(args.role,args.x,args.y,args.engage,args.jumping,max_drop=args.max_drop)
    elif args.action=='face':face(args.role,args.degrees)


if __name__=='__main__':main()
