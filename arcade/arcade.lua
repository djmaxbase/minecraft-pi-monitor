-- BLACKSITE ARCADE OS 3.0 - Create Linked Controller Edition
-- A standalone arcade cabinet for CC:Tweaked Advanced Computers and large Advanced Monitors.
-- Controller receivers: left=LEFT, top=RIGHT, bottom=UP, back=DOWN, front=ACTION.
-- Hold ACTION for 1.2 seconds to open the pause/exit menu.
local native=term.current()
local mon=peripheral.find("monitor")
local dataFile="blacksite_arcade_save"
local oldScores="arcade_scores"
local C=colors
local version="3.0"
local defaults={theme=1,scale=0.5,difficulty=2,sound=true,repeatDelay=0.105,records={},played={},selected=1,oldScoresImported=false}
local data={}
for k,v in pairs(defaults) do data[k]=type(v)=="table" and {} or v end
if fs.exists(dataFile) then
 local f=fs.open(dataFile,"r")
 if f then local ok,d=pcall(textutils.unserialize,f.readAll());f.close();if ok and type(d)=="table" then for k,v in pairs(defaults) do if type(d[k])==type(v) then data[k]=d[k] end end end end
end
if not data.oldScoresImported and fs.exists(oldScores) then
 local f=fs.open(oldScores,"r")
 if f then local ok,d=pcall(textutils.unserialize,f.readAll());f.close();if ok and type(d)=="table" then
  for k,v in pairs(d) do if type(v)=="number" and v>(data.records[k] or 0) then data.records[k]=v end end
 end end
 data.oldScoresImported=true
end
if mon then mon.setTextScale(data.scale);term.redirect(mon) end
local W,H=term.getSize()
if not term.isColor() then term.redirect(native);print("Advanced Computer/Monitor required");return end
math.randomseed(os.epoch("utc")%2147483647)
local speaker=peripheral.find("speaker")
local themes={
 {accent=C.purple,bright=C.cyan,panel=C.gray,edge=C.blue,hot=C.lime},
 {accent=C.blue,bright=C.lightBlue,panel=C.gray,edge=C.cyan,hot=C.yellow},
 {accent=C.green,bright=C.lime,panel=C.gray,edge=C.brown,hot=C.orange}
}
local T=themes[data.theme] or themes[1]
local function save()
 local f=fs.open(dataFile,"w")
 if f then f.write(textutils.serialize(data));f.close() end
end
local function beep(p)
 if data.sound and speaker then pcall(speaker.playSound,"minecraft:block.note_block.pling",0.35,p or 1) end
end
local function rect(x,y,w,h,bg)
 x=math.floor(x);y=math.floor(y);w=math.floor(w);h=math.floor(h)
 local x2=math.min(W,x+w-1);local y2=math.min(H,y+h-1)
 x=math.max(1,x);y=math.max(1,y)
 if x>x2 or y>y2 then return end
 term.setBackgroundColor(bg)
 local line=string.rep(" ",x2-x+1)
 for yy=y,y2 do term.setCursorPos(x,yy);term.write(line) end
end
local function write(x,y,s,fg,bg)
 if y<1 or y>H then return end
 s=tostring(s or "");x=math.floor(x)
 if x<1 then s=s:sub(2-x);x=1 end
 if x>W or #s==0 then return end
 s=s:sub(1,W-x+1)
 term.setTextColor(fg or C.white)
 if bg then term.setBackgroundColor(bg) end
 term.setCursorPos(x,y);term.write(s)
end
local function center(y,s,fg,bg) write(math.floor((W-#tostring(s))/2)+1,y,s,fg,bg) end
local function frame(x,y,w,h,col)
 rect(x,y,w,1,col);rect(x,y+h-1,w,1,col)
 rect(x,y,1,h,col);rect(x+w-1,y,1,h,col)
end
local function dot(x,y,col) rect(x,y,1,1,col) end
local stars={}
for i=1,math.floor(W*H/120) do stars[i]={math.random(2,W-1),math.random(4,H-2)} end
local function clear(bg)
 term.setBackgroundColor(bg or C.black);term.setTextColor(C.white);term.clear()
end
local function shell(title,sub)
 clear(C.black)
 for _,p in ipairs(stars) do dot(p[1],p[2],C.gray) end
 rect(1,1,W,3,T.accent)
 write(3,2,"< B L A C K S I T E // A R C A D E >",C.white,T.accent)
 write(math.max(1,W-12),2,"OS v"..version,C.white,T.accent)
 if title then center(5,title,T.bright) end
 if sub then center(6,sub,C.lightGray) end
end
local function footer(s)
 rect(1,H,W,1,T.accent)
 center(H,s or "ARROWS MOVE  SPACE SELECT",C.white,T.accent)
end
local function hud(title,score,extra,help)
 clear(C.black)
 rect(1,1,W,3,T.accent)
 write(3,2,"BLACKSITE  /  "..title,C.white,T.accent)
 write(math.max(2,W-23),2,"SCORE "..tostring(score or 0),C.yellow,T.accent)
 if extra then center(5,extra,T.bright) end
 footer(help or "ARROWS MOVE  SPACE ACTION  HOLD SPACE PAUSE")
end
local function barValue(x,y,w,value,maxVal,col)
 rect(x,y,w,1,C.gray)
 rect(x,y,math.max(0,math.min(w,math.floor(w*(value/math.max(1,maxVal))))),1,col)
end
local function notice(title,lines)
 shell(title)
 for i,s in ipairs(lines) do center(9+i*2,s,i==1 and T.hot or C.white) end
 footer("SPACE / RIGHT CONTINUE")
end
-- Event-driven Create controller, including held-direction repeat and front-link long press.
local buttonSides={left=keys.left,top=keys.right,bottom=keys.up,back=keys.down,front=keys.space}
local order={"left","top","bottom","back","front"}
local down,repeatAt={},{}
local nextTimer=nil
local holdTimer=nil
local longDone=false
local pending={}
local function queue(k,typ) pending[#pending+1]={typ or "key",k} end
local function timerRepeat()
 local earliest=nil;local now=os.clock()
 for _,side in ipairs(order) do
  if side~="front" and down[side] and repeatAt[side] then
   local d=math.max(0.02,repeatAt[side]-now)
   if not earliest or d<earliest then earliest=d end
  end
 end
 nextTimer=earliest and os.startTimer(earliest) or nil
end
for _,side in ipairs(order) do down[side]=redstone.getInput(side) end
local function poll()
 while true do
  if #pending>0 then local x=table.remove(pending,1);return x[1],x[2] end
  local e,a,b,c=os.pullEvent()
  if e=="redstone" then
   for _,side in ipairs(order) do
    local state=redstone.getInput(side)
    if state and not down[side] then
     queue(buttonSides[side])
     if side=="front" then
      longDone=false;holdTimer=os.startTimer(1.2)
     else repeatAt[side]=os.clock()+0.30 end
    elseif not state and down[side] then
     repeatAt[side]=nil
     if side=="front" then holdTimer=nil end
    end
    down[side]=state
   end
   timerRepeat()
  elseif e=="timer" and a==holdTimer then
   holdTimer=nil
   if down.front and not longDone then longDone=true;return "hold",keys.space end
  elseif e=="timer" and a==nextTimer then
   local now=os.clock()
   for _,side in ipairs(order) do
    if side~="front" and down[side] and repeatAt[side] and now>=repeatAt[side]-0.018 then
     queue(buttonSides[side])
     repeatAt[side]=now+data.repeatDelay
    end
   end
   timerRepeat()
  elseif e=="key" then
   local aliases={[keys.w]=keys.up,[keys.s]=keys.down,[keys.a]=keys.left,[keys.d]=keys.right,[keys.enter]=keys.space}
   return "key",aliases[a] or a
  elseif e=="monitor_touch" then return "touch",{x=b,y=c}
  elseif e=="timer" then return "timer",a end
 end
end
local function waitButton()
 while true do local e,k=poll();if e=="key" then return k end end
end
local function result(g,s,won)
 local score=math.floor(s.score or 0)
 local id=g.id
 local previous=data.records[id] or 0
 if score>previous then data.records[id]=score end
 data.played[id]=(data.played[id] or 0)+1
 save()
 beep(won and 1.8 or 0.6)
 while true do
  shell(won and "VICTORY!" or "GAME OVER","// "..g.name.." //")
  center(10,"SCORE",C.lightGray)
  center(12,tostring(score),T.hot)
  center(15,score>previous and "NEW PERSONAL BEST!" or ("PERSONAL BEST  "..tostring(data.records[id] or 0)),C.yellow)
  center(19,won and "MISSION COMPLETE" or "GAME COMPLETE",T.bright)
  center(H-5,"SPACE: RETRY     LEFT: LIBRARY",C.white)
  footer("SPACE RETRY  /  LEFT RETURN")
  local e,k=poll()
  if e=="key" then
   if k==keys.space or k==keys.right then return "retry"
   elseif k==keys.left or k==keys.q then return "exit" end
  elseif e=="hold" then return "exit" end
 end
end
local function pauseMenu()
 local choice=1
 local opts={"RESUME GAME","RESTART GAME","EXIT TO LIBRARY"}
 while true do
  shell("GAME PAUSED","CONTROLLER MENU")
  for i,s in ipairs(opts) do
   local y=10+i*4
   rect(math.floor(W/2)-17,y,34,3,i==choice and T.accent or C.gray)
   center(y+1,(i==choice and "> " or "  ")..s,C.white)
  end
  footer("UP/DOWN CHOOSE   SPACE CONFIRM")
  local e,k=poll()
  if e=="key" then
   if k==keys.up then choice=choice==1 and 3 or choice-1
   elseif k==keys.down then choice=choice==3 and 1 or choice+1
   elseif k==keys.space or k==keys.right then return choice
   elseif k==keys.q then return 1 end
  end
 end
end
local function endState(s,won) s.done=true;s.won=won or false end
local function session(g)
 while true do
  local s=g.init()
  local ticking=os.startTimer(0.085)
  local exit=false
  while not exit do
   g.draw(s)
   if s.done then
    local r=result(g,s,s.won)
    if r=="retry" then exit=true
    else return end
   else
    local e,k=poll()
    if e=="hold" and k==keys.space or (e=="key" and k==keys.p) then
     local p=pauseMenu()
     if p==2 then exit=true
     elseif p==3 then return end
     ticking=os.startTimer(0.085)
    elseif e=="key" then
     if k==keys.q or k==keys.backspace then return end
     if g.key then g.key(s,k) end
    elseif e=="timer" and k==ticking then
     s.tick=(s.tick or 0)+1
     if g.tick then g.tick(s) end
     ticking=os.startTimer(0.085)
    end
   end
  end
 end
end
local games={}
local function add(id,name,cat,icon,tag,init,draw,key,tick)
 games[#games+1]={id=id,name=name,category=cat,icon=icon,tag=tag,init=init,draw=draw,key=key,tick=tick}
end
local function bounding(w,h)
 return math.floor((W-w)/2)+1,math.floor((H-h)/2)+1
end
local function cell(x,y,w,h,col) rect(x,y,w,h,col) end
local function rnd(n) return math.random(n) end
local function speed(n) return math.max(1,math.floor(n/(data.difficulty==3 and 1.4 or data.difficulty==1 and 0.7 or 1))) end
-- 01 / SNAKE
add("SNAKE","NEON SNAKE","ARCADE","o~~","EAT / GROW / SURVIVE",
 function()
  local gw=math.min(48,W-12);local gh=math.min(22,H-11);local x,y=bounding(gw,gh)
  return {w=gw,h=gh,x=x,y=y,body={{x=math.floor(gw/2),y=math.floor(gh/2)}},dx=1,dy=0,fx=4,fy=4,score=0,tick=0}
 end,
 function(s)
  hud("NEON SNAKE",s.score,"LENGTH "..#s.body,"ARROWS STEER  /  HOLD SPACE PAUSE")
  frame(s.x-1,s.y-1,s.w+2,s.h+2,T.edge)
  for _,p in ipairs(s.body) do dot(s.x+p.x-1,s.y+p.y-1,p==s.body[1] and C.lime or C.green) end
  dot(s.x+s.fx-1,s.y+s.fy-1,C.red)
 end,
 function(s,k)
  if k==keys.up and s.dy~=1 then s.nx,s.ny=0,-1
  elseif k==keys.down and s.dy~=-1 then s.nx,s.ny=0,1
  elseif k==keys.left and s.dx~=1 then s.nx,s.ny=-1,0
  elseif k==keys.right and s.dx~=-1 then s.nx,s.ny=1,0 end
 end,
 function(s)
  if s.tick%speed(2)~=0 then return end
  if s.nx then s.dx,s.dy=s.nx,s.ny;s.nx=nil end
  local h=s.body[1];local x,y=h.x+s.dx,h.y+s.dy
  if x<1 or y<1 or x>s.w or y>s.h then return endState(s) end
  local eat=(x==s.fx and y==s.fy)
  for i,p in ipairs(s.body) do if (eat or i<#s.body) and p.x==x and p.y==y then return endState(s) end end
  table.insert(s.body,1,{x=x,y=y})
  if eat then
   s.score=s.score+10;beep(1.4)
   for n=1,200 do
    local fx,fy=rnd(s.w),rnd(s.h);local free=true
    for _,p in ipairs(s.body) do if p.x==fx and p.y==fy then free=false;break end end
    if free then s.fx,s.fy=fx,fy;break end
   end
  else table.remove(s.body) end
 end)
-- 02 / PONG
add("PONG","PIXEL PONG","ARCADE","|o|","PLAYER VS CPU",
 function() return {w=math.min(58,W-12),h=math.min(23,H-12),y=8,ai=8,bx=20,by=8,vx=-1,vy=1,score=0,tick=0,lives=3} end,
 function(s)
  local x,y=bounding(s.w,s.h)
  hud("PIXEL PONG",s.score,"LIVES "..s.lives,"UP/DOWN PADDLE  /  HOLD SPACE PAUSE")
  frame(x-1,y-1,s.w+2,s.h+2,T.edge)
  for i=-2,2 do dot(x+1,y+s.y+i,C.lime);dot(x+s.w-2,y+s.ai+i,C.red) end
  dot(x+s.bx,y+s.by,C.white)
  for yy=1,s.h-1,2 do dot(x+math.floor(s.w/2),y+yy,C.gray) end
 end,
 function(s,k)
  if k==keys.up then s.y=math.max(3,s.y-2) elseif k==keys.down then s.y=math.min(s.h-3,s.y+2) end
 end,
 function(s)
  if s.tick%speed(2)~=0 then return end
  s.bx=s.bx+s.vx;s.by=s.by+s.vy
  if s.by<=1 or s.by>=s.h-1 then s.vy=-s.vy;s.by=math.max(1,math.min(s.h-1,s.by)) end
  if s.bx<=3 then
   if math.abs(s.by-s.y)<=2 then s.vx=1;s.score=s.score+1;beep(1.2)
   else s.lives=s.lives-1;if s.lives<=0 then return endState(s) end
    s.bx=math.floor(s.w/2);s.by=math.floor(s.h/2);s.vx=-1
   end
  end
  if s.bx>=s.w-3 then s.vx=-1;beep(0.8) end
  if s.ai<s.by then s.ai=math.min(s.h-3,s.ai+1)
  elseif s.ai>s.by then s.ai=math.max(3,s.ai-1) end
 end)
-- 03 / BLOCK DROP
local shapes={
 {{0,0},{1,0},{0,1},{1,1}},
 {{0,0},{1,0},{2,0},{3,0}},
 {{0,0},{1,0},{2,0},{1,1}},
 {{0,0},{0,1},{1,1},{2,1}},
 {{1,0},{2,0},{0,1},{1,1}},
 {{0,0},{0,1},{0,2},{1,2}},
 {{1,0},{1,1},{1,2},{0,2}}
}
local blockColors={C.yellow,C.cyan,C.purple,C.red,C.lime,C.orange,C.blue}
local function newBlock(s)
 s.kind=rnd(#shapes);s.piece={}
 for _,p in ipairs(shapes[s.kind]) do s.piece[#s.piece+1]={p[1],p[2]} end
 s.px=4;s.py=1
end
local function blockFits(s,dx,dy,piece)
 for _,p in ipairs(piece or s.piece) do
  local x,y=dx+p[1],dy+p[2]
  if x<1 or x>10 or y>s.h or (y>=1 and s.board[y][x]) then return false end
 end
 return true
end
local function blockDown(s)
 if blockFits(s,s.px,s.py+1) then s.py=s.py+1;return end
 for _,p in ipairs(s.piece) do
  local x,y=s.px+p[1],s.py+p[2];if y>=1 and y<=s.h then s.board[y][x]=blockColors[s.kind] end
 end
 local row=s.h
 while row>=1 do
  local full=true
  for x=1,10 do if not s.board[row][x] then full=false;break end end
  if full then
   table.remove(s.board,row);table.insert(s.board,1,{})
   s.score=s.score+100;beep(1.65)
  else row=row-1 end
 end
 newBlock(s)
 if not blockFits(s,s.px,s.py) then endState(s) end
end
add("BLOCKS","BLOCK DROP","ARCADE","[][]","STACK THE BLOCKS",
 function()
  local s={h=math.min(23,H-11),board={},score=0,tick=0}
  for y=1,s.h do s.board[y]={} end
  newBlock(s);return s
 end,
 function(s)
  local x,y=bounding(22,s.h)
  hud("BLOCK DROP",s.score,"10 x "..s.h.." GRID","LEFT/RIGHT MOVE   UP ROTATE  SPACE DROP")
  frame(x-1,y-1,22,s.h+2,T.edge)
  for yy=1,s.h do for xx=1,10 do
   rect(x+(xx-1)*2,y+yy-1,2,1,s.board[yy][xx] or C.gray)
  end end
  for _,p in ipairs(s.piece) do
   local xx,yy=s.px+p[1],s.py+p[2]
   if yy>=1 and yy<=s.h then rect(x+(xx-1)*2,y+yy-1,2,1,blockColors[s.kind]) end
  end
 end,
 function(s,k)
  if k==keys.left and blockFits(s,s.px-1,s.py) then s.px=s.px-1
  elseif k==keys.right and blockFits(s,s.px+1,s.py) then s.px=s.px+1
  elseif k==keys.down then blockDown(s)
  elseif k==keys.space then
   while blockFits(s,s.px,s.py+1) do s.py=s.py+1 end
   blockDown(s)
  elseif k==keys.up then
   local p={};local minx,miny=100,100
   for _,v in ipairs(s.piece) do local a,b=-v[2],v[1];p[#p+1]={a,b};minx=math.min(a,minx);miny=math.min(b,miny) end
   for _,v in ipairs(p) do v[1]=v[1]-minx;v[2]=v[2]-miny end
   if blockFits(s,s.px,s.py,p) then s.piece=p end
  end
 end,
 function(s) if s.tick%speed(6)==0 then blockDown(s) end end)
-- 04 / BREAKOUT
add("BREAKOUT","BREAKOUT","ARCADE","#####","SMASH NEON BRICKS",
 function()
  local s={w=math.min(58,W-10),h=math.min(24,H-11),score=0,lives=3,tick=0,bricks={}}
  s.px=math.floor(s.w/2);s.bx=s.px;s.by=s.h-3;s.vx=1;s.vy=-1
  for y=3,7 do s.bricks[y]={};for x=3,s.w-2 do if x%7~=0 then s.bricks[y][x]=blockColors[(y-3)%7+1] end end end
  return s
 end,
 function(s)
  local x,y=bounding(s.w,s.h)
  hud("BREAKOUT",s.score,"LIVES "..s.lives,"LEFT/RIGHT MOVE THE PADDLE")
  frame(x-1,y-1,s.w+2,s.h+2,T.edge)
  for yy,row in pairs(s.bricks) do for xx,col in pairs(row) do dot(x+xx-1,y+yy-1,col) end end
  rect(x+s.px-4,y+s.h-2,9,1,C.lime)
  dot(x+s.bx-1,y+s.by-1,C.white)
 end,
 function(s,k)
  if k==keys.left then s.px=math.max(6,s.px-3)
  elseif k==keys.right then s.px=math.min(s.w-5,s.px+3) end
 end,
 function(s)
  if s.tick%speed(1)~=0 then return end
  local nx,ny=s.bx+s.vx,s.by+s.vy
  if nx<=1 or nx>=s.w then s.vx=-s.vx;nx=s.bx+s.vx end
  if ny<=1 then s.vy=1;ny=s.by+s.vy end
  if s.bricks[ny] and s.bricks[ny][nx] then
   s.bricks[ny][nx]=nil;s.score=s.score+10;beep(1.4);s.vy=-s.vy;ny=s.by+s.vy
  end
  if ny>=s.h-1 then
   if math.abs(nx-s.px)<=4 then
    s.vy=-1;ny=s.h-2
    if nx<s.px then s.vx=-1 elseif nx>s.px then s.vx=1 end
   else
    s.lives=s.lives-1;if s.lives<=0 then return endState(s) end
    nx=s.px;ny=s.h-3;s.vy=-1
   end
  end
  s.bx,s.by=nx,ny
  local any=false
  for _,row in pairs(s.bricks) do if next(row) then any=true;break end end
  if not any then endState(s,true) end
 end)
-- 05 / SPACE BLASTER
add("INVADERS","SPACE BLASTER","ARCADE","/^^\\","DEFEND THE GALAXY",
 function()
  local s={w=math.min(58,W-10),h=math.min(24,H-11),score=0,lives=3,tick=0,shots={},aliens={},dir=1,px=30}
  s.px=math.floor(s.w/2)
  for y=3,8,2 do for x=5,s.w-5,5 do s.aliens[#s.aliens+1]={x=x,y=y} end end
  return s
 end,
 function(s)
  local x,y=bounding(s.w,s.h)
  hud("SPACE BLASTER",s.score,"SHIELDS "..s.lives.."   ENEMIES "..#s.aliens,"LEFT/RIGHT AIM   SPACE FIRE")
  frame(x-1,y-1,s.w+2,s.h+2,T.edge)
  for _,a in ipairs(s.aliens) do write(x+a.x-1,y+a.y-1,"{M}",C.red) end
  for _,b in ipairs(s.shots) do dot(x+b.x-1,y+b.y-1,C.yellow) end
  write(x+s.px-2,y+s.h-2,"/^\\",C.lime)
 end,
 function(s,k)
  if k==keys.left then s.px=math.max(3,s.px-2)
  elseif k==keys.right then s.px=math.min(s.w-3,s.px+2)
  elseif k==keys.space and #s.shots<4 then
   s.shots[#s.shots+1]={x=s.px,y=s.h-3};beep(1.5)
  end
 end,
 function(s)
  if s.tick%speed(2)==0 then
   for i=#s.shots,1,-1 do
    local b=s.shots[i];b.y=b.y-1;local hit=false
    for j=#s.aliens,1,-1 do
     local a=s.aliens[j]
     if math.abs(b.x-a.x)<=1 and b.y==a.y then
      table.remove(s.aliens,j);s.score=s.score+25;hit=true;break
     end
    end
    if hit or b.y<1 then table.remove(s.shots,i) end
   end
  end
  if s.tick%speed(7)==0 then
   local hitEdge=false
   for _,a in ipairs(s.aliens) do if a.x+s.dir>=s.w-3 or a.x+s.dir<=2 then hitEdge=true end end
   if hitEdge then s.dir=-s.dir end
   for _,a in ipairs(s.aliens) do a.x=a.x+s.dir;if hitEdge then a.y=a.y+1 end
    if a.y>=s.h-3 then return endState(s) end
   end
  end
  if #s.aliens==0 then endState(s,true) end
 end)
-- 06 / FLAPPY PIXEL
add("FLAPPY","FLAPPY PIXEL","REFLEX",">o>","ONE-TAP FLIGHT",
 function() return {w=math.min(56,W-12),h=math.min(23,H-12),bird=10,velocity=0,pipes={},score=0,tick=0} end,
 function(s)
  local x,y=bounding(s.w,s.h)
  hud("FLAPPY PIXEL",s.score,"KEEP THE PIXEL FLYING","SPACE / UP FLAP")
  frame(x-1,y-1,s.w+2,s.h+2,T.edge)
  for _,p in ipairs(s.pipes) do
   for yy=1,s.h do if yy<p.gap or yy>p.gap+6 then dot(x+p.x-1,y+yy-1,C.green) end end
  end
  write(x+7,y+math.floor(s.bird)-1,"<o>",C.yellow)
 end,
 function(s,k)
  if k==keys.space or k==keys.up then s.velocity=-2.5;beep(1.4) end
 end,
 function(s)
  if s.tick%speed(2)~=0 then return end
  s.velocity=math.min(2,s.velocity+0.6);s.bird=s.bird+s.velocity
  if s.bird<1 or s.bird>s.h then return endState(s) end
  if s.tick%(speed(2)*14)==0 then
   s.pipes[#s.pipes+1]={x=s.w-2,gap=math.random(3,s.h-9),passed=false}
  end
  for i=#s.pipes,1,-1 do
   local p=s.pipes[i];p.x=p.x-1
   if p.x>=8 and p.x<=10 and (s.bird<p.gap or s.bird>p.gap+6) then return endState(s) end
   if p.x<8 and not p.passed then p.passed=true;s.score=s.score+10;beep(1.2) end
   if p.x<1 then table.remove(s.pipes,i) end
  end
 end)
-- 07 / METEOR DODGE
add("DODGE","METEOR DODGE","REFLEX","*!!","SURVIVE THE STORM",
 function() return {w=math.min(56,W-12),h=math.min(24,H-11),px=27,rocks={},score=0,tick=0} end,
 function(s)
  local x,y=bounding(s.w,s.h)
  hud("METEOR DODGE",s.score,"DODGE OR GET CRUSHED","LEFT / RIGHT DODGE")
  frame(x-1,y-1,s.w+2,s.h+2,T.edge)
  for _,p in ipairs(s.rocks) do dot(x+p.x-1,y+p.y-1,C.red) end
  write(x+s.px-1,y+s.h-2,"A",C.lime)
 end,
 function(s,k)
  if k==keys.left then s.px=math.max(2,s.px-2)
  elseif k==keys.right then s.px=math.min(s.w-2,s.px+2) end
 end,
 function(s)
  if s.tick%speed(2)~=0 then return end
  if s.tick%(speed(2)*4)==0 then s.rocks[#s.rocks+1]={x=rnd(s.w-4)+2,y=1} end
  for i=#s.rocks,1,-1 do
   local p=s.rocks[i];p.y=p.y+1
   if p.y==s.h-1 and math.abs(p.x-s.px)<=1 then return endState(s) end
   if p.y>=s.h then table.remove(s.rocks,i);s.score=s.score+5 end
  end
 end)
-- 08 / NEON RACER
add("RACER","NEON RACER","REFLEX","/||\\","DODGE TRAFFIC",
 function()
  return {w=36,h=math.min(23,H-12),lane=2,cars={},score=0,tick=0}
 end,
 function(s)
  local x,y=bounding(s.w,s.h)
  hud("NEON RACER",s.score,"ROAD SPEED "..(data.difficulty+1),"LEFT / RIGHT CHANGE LANES")
  frame(x-1,y-1,s.w+2,s.h+2,T.edge)
  for yy=1,s.h do for line=1,2 do if yy%3~=0 then dot(x+line*12-1,y+yy-1,C.yellow) end end end
  for _,p in ipairs(s.cars) do rect(x+(p.lane-1)*12+4,y+p.y-1,4,2,C.red) end
  rect(x+(s.lane-1)*12+4,y+s.h-4,4,2,C.lime)
 end,
 function(s,k)
  if k==keys.left then s.lane=math.max(1,s.lane-1)
  elseif k==keys.right then s.lane=math.min(3,s.lane+1) end
 end,
 function(s)
  if s.tick%speed(2)~=0 then return end
  if s.tick%(speed(2)*8)==0 then s.cars[#s.cars+1]={lane=rnd(3),y=1} end
  for i=#s.cars,1,-1 do
   local p=s.cars[i];p.y=p.y+1
   if p.lane==s.lane and p.y>=s.h-5 and p.y<=s.h-2 then return endState(s) end
   if p.y>s.h then table.remove(s.cars,i);s.score=s.score+10 end
  end
 end)
-- 09 / 2048
local function spawnTile(s)
 local empty={}
 for y=1,4 do for x=1,4 do if s.board[y][x]==0 then empty[#empty+1]={x,y} end end end
 if #empty>0 then local p=empty[rnd(#empty)];s.board[p[2]][p[1]]=rnd(10)==1 and 4 or 2 end
end
local function slide2048(s,k)
 local before=textutils.serialize(s.board)
 local function mergeLine(v)
  local a={}
  for _,n in ipairs(v) do if n>0 then a[#a+1]=n end end
  local b={};local i=1
  while i<=#a do
   if a[i]==a[i+1] then b[#b+1]=a[i]*2;s.score=s.score+a[i]*2;i=i+2
   else b[#b+1]=a[i];i=i+1 end
  end
  while #b<4 do b[#b+1]=0 end
  return b
 end
 for i=1,4 do
  local line={}
  for j=1,4 do
   local x,y=j,i
   if k==keys.right then x=5-j
   elseif k==keys.up then x=i;y=j
   elseif k==keys.down then x=i;y=5-j end
   line[j]=s.board[y][x]
  end
  local merged=mergeLine(line)
  for j=1,4 do
   local x,y=j,i
   if k==keys.right then x=5-j
   elseif k==keys.up then x=i;y=j
   elseif k==keys.down then x=i;y=5-j end
   s.board[y][x]=merged[j]
  end
 end
 if textutils.serialize(s.board)~=before then spawnTile(s);beep(1.2) end
 local move=false
 for y=1,4 do for x=1,4 do
  local n=s.board[y][x]
  if n==2048 then return endState(s,true) end
  if n==0 or x<4 and n==s.board[y][x+1] or y<4 and n==s.board[y+1][x] then move=true end
 end end
 if not move then endState(s) end
end
add("2048","2048","PUZZLE","2+2","MERGE TO 2048",
 function()
  local s={board={},score=0,tick=0}
  for y=1,4 do s.board[y]={0,0,0,0} end
  spawnTile(s);spawnTile(s);return s
 end,
 function(s)
  local x,y=bounding(36,21)
  hud("2048",s.score,"MERGE IDENTICAL NUMBERS","ARROWS SLIDE ALL TILES")
  for yy=1,4 do for xx=1,4 do
   local n=s.board[yy][xx];local col=n==0 and C.gray or n<8 and C.brown or n<32 and C.orange or n<128 and C.red or n<512 and C.purple or C.lime
   rect(x+(xx-1)*9,y+(yy-1)*5,8,4,col)
   if n>0 then write(x+(xx-1)*9+math.floor((8-#tostring(n))/2),y+(yy-1)*5+1,n,C.white,col) end
  end end
 end,
 function(s,k) if k==keys.left or k==keys.right or k==keys.up or k==keys.down then slide2048(s,k) end end)
-- 10 / MEMORY MATCH
add("MEMORY","MEMORY MATCH","PUZZLE","??","FIND ALL THE PAIRS",
 function()
  local pairs={};for i=1,8 do pairs[#pairs+1]=i;pairs[#pairs+1]=i end
  for i=#pairs,2,-1 do local j=rnd(i);pairs[i],pairs[j]=pairs[j],pairs[i] end
  return {deck=pairs,found={},shown={},cursor=1,score=0,tries=0,tick=0,hide=0}
 end,
 function(s)
  hud("MEMORY MATCH",s.score,"TRIES "..s.tries.."   PAIRS "..(s.score/10).."/8","ARROWS SELECT  SPACE FLIP")
  local x,y=bounding(39,21)
  for i=1,16 do
   local xx,yy=(i-1)%4,math.floor((i-1)/4)
   local active=s.cursor==i;local open=s.found[i] or s.shown[i]
   local col=s.found[i] and C.green or active and T.accent or C.gray
   rect(x+xx*10,y+yy*5,9,4,col)
   write(x+xx*10+4,y+yy*5+1,open and tostring(s.deck[i]) or "?",C.white,col)
  end
 end,
 function(s,k)
  if k==keys.left then s.cursor=math.max(1,s.cursor-1)
  elseif k==keys.right then s.cursor=math.min(16,s.cursor+1)
  elseif k==keys.up then s.cursor=math.max(1,s.cursor-4)
  elseif k==keys.down then s.cursor=math.min(16,s.cursor+4)
  elseif k==keys.space and not s.found[s.cursor] and not s.shown[s.cursor] and s.hide==0 then
   s.shown[s.cursor]=true
   local two={}
   for i=1,16 do if s.shown[i] then two[#two+1]=i end end
   if #two==2 then
    s.tries=s.tries+1
    if s.deck[two[1]]==s.deck[two[2]] then
     s.found[two[1]]=true;s.found[two[2]]=true;s.shown={}
     s.score=s.score+10;beep(1.5)
     if s.score==80 then endState(s,true) end
    else s.hide=s.tick+9 end
   end
  end
 end,
 function(s) if s.hide>0 and s.tick>=s.hide then s.shown={};s.hide=0 end end)
-- 11 / MINEFIELD
local function adjacent(s,x,y)
 local n=0
 for dy=-1,1 do for dx=-1,1 do if s.mines[(y+dy)..":"..(x+dx)] then n=n+1 end end end
 return n
end
local function revealMine(s,x,y)
 if x<1 or y<1 or x>8 or y>8 then return end
 local key=y..":"..x
 if s.revealed[key] then return end
 s.revealed[key]=true;s.open=s.open+1
 if s.mines[key] then return endState(s) end
 if adjacent(s,x,y)==0 then
  for dy=-1,1 do for dx=-1,1 do
   if dx~=0 or dy~=0 then revealMine(s,x+dx,y+dy) end
  end end
 end
 if s.open==54 then s.score=540;endState(s,true) end
end
add("MINES","MINEFIELD","PUZZLE","[*]","AVOID THE MINES",
 function()
  local s={mines={},revealed={},cursor=1,score=0,open=0,tick=0,started=false}
  return s
 end,
 function(s)
  hud("MINEFIELD",s.score,"SAFE CELLS "..s.open.."/54","ARROWS TARGET   SPACE REVEAL")
  local x,y=bounding(49,25)
  for i=1,64 do
   local xx,yy=(i-1)%8+1,math.floor((i-1)/8)+1
   local k=yy..":"..xx;local shown=s.revealed[k];local num=shown and adjacent(s,xx,yy) or 0
   local col=s.cursor==i and T.accent or shown and C.lightGray or C.gray
   rect(x+(xx-1)*6,y+(yy-1)*3,5,2,col)
   write(x+(xx-1)*6+2,y+(yy-1)*3,shown and (s.mines[k] and "*" or num>0 and tostring(num) or " ") or "#",shown and C.black or C.white,col)
  end
 end,
 function(s,k)
  if k==keys.left then s.cursor=math.max(1,s.cursor-1)
  elseif k==keys.right then s.cursor=math.min(64,s.cursor+1)
  elseif k==keys.up then s.cursor=math.max(1,s.cursor-8)
  elseif k==keys.down then s.cursor=math.min(64,s.cursor+8)
  elseif k==keys.space then
   local x,y=(s.cursor-1)%8+1,math.floor((s.cursor-1)/8)+1
   if not s.started then
    s.started=true
    local count=0
    while count<10 do
     local a,b=rnd(8),rnd(8);local key2=b..":"..a
     if not s.mines[key2] and (math.abs(a-x)>1 or math.abs(b-y)>1) then
      s.mines[key2]=true;count=count+1
     end
    end
   end
   revealMine(s,x,y);s.score=s.open*10
  end
 end)
-- 12 / LIGHTS OUT
add("LIGHTS","LIGHTS OUT","PUZZLE","O*O","TURN OFF THE GRID",
 function()
  local s={grid={},cursor=13,score=0,tick=0,steps=0}
  for i=1,25 do s.grid[i]=false end
  local function flip(i)
   local row=math.floor((i-1)/5);local col=(i-1)%5
   for _,v in ipairs({{0,0},{-1,0},{1,0},{0,-1},{0,1}}) do
    local xx,yy=col+v[1],row+v[2]
    if xx>=0 and xx<5 and yy>=0 and yy<5 then local j=yy*5+xx+1;s.grid[j]=not s.grid[j] end
   end
  end
  for i=1,11 do flip(rnd(25)) end
  return s
 end,
 function(s)
  hud("LIGHTS OUT",s.score,"MOVES "..s.steps,"ARROWS SELECT  SPACE TOGGLE")
  local x,y=bounding(39,23)
  for i=1,25 do
   local xx=(i-1)%5;local yy=math.floor((i-1)/5)
   local col=s.grid[i] and C.yellow or C.gray
   rect(x+xx*8,y+yy*4,7,3,col)
   if s.cursor==i then frame(x+xx*8,y+yy*4,7,3,T.accent) end
  end
 end,
 function(s,k)
  if k==keys.left then s.cursor=math.max(1,s.cursor-1)
  elseif k==keys.right then s.cursor=math.min(25,s.cursor+1)
  elseif k==keys.up then s.cursor=math.max(1,s.cursor-5)
  elseif k==keys.down then s.cursor=math.min(25,s.cursor+5)
  elseif k==keys.space then
   local row,col=math.floor((s.cursor-1)/5),(s.cursor-1)%5
   for _,v in ipairs({{0,0},{-1,0},{1,0},{0,-1},{0,1}}) do
    local x,y=col+v[1],row+v[2]
    if x>=0 and x<5 and y>=0 and y<5 then local j=y*5+x+1;s.grid[j]=not s.grid[j] end
   end
   s.steps=s.steps+1;s.score=math.max(0,500-s.steps*10)
   local on=false
   for _,v in ipairs(s.grid) do if v then on=true;break end end
   if not on then endState(s,true) end
  end
 end)
-- 13 / MAZE ESCAPE
local function mazeGenerate()
 local m={}
 for y=1,15 do m[y]={};for x=1,31 do m[y][x]=true end end
 local stack={{2,2}};m[2][2]=false
 while #stack>0 do
  local p=stack[#stack];local candidates={}
  for _,d in ipairs({{2,0},{-2,0},{0,2},{0,-2}}) do
   local x,y=p[1]+d[1],p[2]+d[2]
   if x>1 and x<31 and y>1 and y<15 and m[y][x] then
    candidates[#candidates+1]={x,y,d[1],d[2]}
   end
  end
  if #candidates==0 then table.remove(stack)
  else local c=candidates[rnd(#candidates)]
   m[p[2]+c[4]/2][p[1]+c[3]/2]=false
   m[c[2]][c[1]]=false;stack[#stack+1]={c[1],c[2]}
  end
 end
 m[14][30]=false
 return m
end
add("MAZE","MAZE ESCAPE","ADVENTURE","##>","FIND THE EXIT",
 function() return {map=mazeGenerate(),px=2,py=2,score=2000,steps=0,tick=0} end,
 function(s)
  hud("MAZE ESCAPE",s.score,"STEPS "..s.steps,"ARROWS MOVE  /  REACH GREEN EXIT")
  local x,y=bounding(31,15)
  for yy=1,15 do for xx=1,31 do
   if s.map[yy][xx] then dot(x+xx-1,y+yy-1,T.edge) end
  end end
  dot(x+29,y+12,C.lime)
  dot(x+s.px-1,y+s.py-1,C.yellow)
 end,
 function(s,k)
  local dx,dy=0,0
  if k==keys.left then dx=-1 elseif k==keys.right then dx=1
  elseif k==keys.up then dy=-1 elseif k==keys.down then dy=1 else return end
  local x,y=s.px+dx,s.py+dy
  if s.map[y] and s.map[y][x]==false then
   s.px,s.py=x,y;s.steps=s.steps+1;s.score=math.max(100,2000-s.steps*10)
   if x==30 and y==14 then endState(s,true) end
  end
 end)
-- 14 / SIMON SIGNAL
local arrows={"UP","RIGHT","DOWN","LEFT"}
local arrowColors={C.cyan,C.lime,C.orange,C.purple}
add("SIMON","SIMON SIGNAL","PUZZLE","<>^v","REMEMBER THE SEQUENCE",
 function() return {seq={rnd(4)},phase="watch",index=1,show=1,cool=0,score=0,tick=0} end,
 function(s)
  hud("SIMON SIGNAL",s.score,"ROUND "..#s.seq.."    "..(s.phase=="watch" and "WATCH CLOSELY" or "REPEAT THE SIGNAL"),"FOLLOW THE COLORED ARROWS")
  local positions={{-12,-6},{3,-1},{-12,4},{-27,-1}}
  local cx,cy=math.floor(W/2),math.floor(H/2)
  for i=1,4 do
   local p=positions[i];local on=(s.phase=="watch" and s.seq[s.show]==i and s.cool<5)
   rect(cx+p[1],cy+p[2],24,4,on and arrowColors[i] or C.gray)
   write(cx+p[1]+math.floor((24-#arrows[i])/2),cy+p[2]+1,arrows[i],C.white)
  end
  center(H-3,s.phase=="watch" and "OBSERVE THE PATTERN" or ("INPUT "..s.index.."/"..#s.seq),T.hot)
 end,
 function(s,k)
  if s.phase~="input" then return end
  local v=k==keys.up and 1 or k==keys.right and 2 or k==keys.down and 3 or k==keys.left and 4 or nil
  if not v then return end
  if v~=s.seq[s.index] then return endState(s) end
  s.index=s.index+1;beep(0.8+v/5)
  if s.index>#s.seq then
   s.score=s.score+100
   if #s.seq>=12 then return endState(s,true) end
   s.seq[#s.seq+1]=rnd(4);s.phase="watch";s.show=1;s.cool=0;s.index=1
  end
 end,
 function(s)
  if s.phase=="watch" then
   s.cool=s.cool+1
   if s.cool>=10 then
    s.cool=0;s.show=s.show+1
    if s.show>#s.seq then s.phase="input" end
   end
  end
 end)
-- 15 / REACTION LAB
add("REACTION","REACTION LAB","REFLEX","!!!","HOW FAST ARE YOU?",
 function() return {round=1,phase="wait",start=0,ready=18+rnd(20),score=0,tick=0,last=0} end,
 function(s)
  hud("REACTION LAB",s.score,"ROUND "..s.round.."/5","SPACE WHEN GREEN / DON'T JUMP EARLY")
  local col=s.phase=="wait" and C.red or s.phase=="go" and C.lime or C.blue
  local msg=s.phase=="wait" and "WAIT..." or s.phase=="go" and "PRESS SPACE!" or (s.last.." ms")
  rect(math.floor(W/2)-18,math.floor(H/2)-4,36,9,col)
  center(math.floor(H/2),msg,C.white,col)
 end,
 function(s,k)
  if k~=keys.space then return end
  if s.phase=="wait" then
   s.last=999;s.score=math.max(0,s.score-100);s.phase="result";s.ready=s.tick+10;beep(0.5)
  elseif s.phase=="go" then
   s.last=math.max(1,os.epoch("utc")-s.start)
   s.score=s.score+math.max(0,1000-s.last);s.phase="result";s.ready=s.tick+14
   beep(1.7)
  end
 end,
 function(s)
  if s.phase=="wait" and s.tick>=s.ready then s.phase="go";s.start=os.epoch("utc");beep(1.8)
  elseif s.phase=="result" and s.tick>=s.ready then
   if s.round>=5 then return endState(s,s.score>=2500) end
   s.round=s.round+1;s.phase="wait";s.ready=s.tick+18+rnd(20)
  end
 end)
-- 16 / WHACK-A-MOB
add("WHACK","WHACK-A-MOB","REFLEX","[M]","HIT THE MOBS",
 function() return {cursor=5,mob=rnd(9),score=0,misses=0,tick=0,time=360} end,
 function(s)
  hud("WHACK-A-MOB",s.score,"TIME "..math.ceil(math.max(0,s.time)/12).."  MISSES "..s.misses,"ARROWS AIM   SPACE WHACK")
  local x,y=bounding(43,21)
  for i=1,9 do
   local xx=(i-1)%3;local yy=math.floor((i-1)/3)
   local col=i==s.cursor and T.accent or C.gray
   rect(x+xx*14,y+yy*7,12,5,col)
   if i==s.mob then write(x+xx*14+4,y+yy*7+2,"[M]",C.lime,col)
   else write(x+xx*14+5,y+yy*7+2,".",C.lightGray,col) end
  end
 end,
 function(s,k)
  local p=s.cursor
  if k==keys.left and p%3~=1 then s.cursor=p-1
  elseif k==keys.right and p%3~=0 then s.cursor=p+1
  elseif k==keys.up and p>3 then s.cursor=p-3
  elseif k==keys.down and p<7 then s.cursor=p+3
  elseif k==keys.space then
   if p==s.mob then s.score=s.score+20;s.mob=rnd(9);beep(1.6)
   else s.misses=s.misses+1;s.score=math.max(0,s.score-5);beep(0.7) end
  end
 end,
 function(s)
  s.time=s.time-1
  if s.tick%16==0 then s.mob=rnd(9) end
  if s.time<=0 then endState(s,s.score>=180) end
 end)
-- 17 / CONNECT FOUR
local function c4Winner(board)
 for y=1,6 do for x=1,7 do
  local v=board[y][x]
  if v~=0 then
   for _,d in ipairs({{1,0},{0,1},{1,1},{1,-1}}) do
    local ok=true
    for n=1,3 do
     local xx,yy=x+n*d[1],y+n*d[2]
     if yy<1 or yy>6 or xx<1 or xx>7 or board[yy][xx]~=v then ok=false;break end
    end
    if ok then return v end
   end
  end
 end end
 return nil
end
local function c4Drop(s,col,piece)
 for y=6,1,-1 do
  if s.board[y][col]==0 then s.board[y][col]=piece;return true end
 end
 return false
end
add("CONNECT4","CONNECT FOUR","PARTY","OOOO","BEAT THE ROBOT",
 function()
  local s={board={},col=4,score=0,tick=0,turn=1,moves=0}
  for y=1,6 do s.board[y]={0,0,0,0,0,0,0} end
  return s
 end,
 function(s)
  hud("CONNECT FOUR",s.score,"YOU: RED   CPU: YELLOW","LEFT/RIGHT COLUMN   SPACE DROP")
  local x,y=bounding(43,23)
  rect(x,y,43,23,C.blue)
  for yy=1,6 do for xx=1,7 do
   local v=s.board[yy][xx];local col=v==1 and C.red or v==2 and C.yellow or C.black
   rect(x+2+(xx-1)*6,y+2+(yy-1)*3,4,2,col)
  end end
  write(x+2+(s.col-1)*6,y,"VV",C.lime,C.blue)
 end,
 function(s,k)
  if k==keys.left then s.col=math.max(1,s.col-1)
  elseif k==keys.right then s.col=math.min(7,s.col+1)
  elseif k==keys.space then
   if not c4Drop(s,s.col,1) then return end
   s.moves=s.moves+1
   if c4Winner(s.board)==1 then s.score=1000;return endState(s,true) end
   if s.moves>=42 then s.score=200;return endState(s,true) end
   local possible={}
   for i=1,7 do if s.board[1][i]==0 then possible[#possible+1]=i end end
   if #possible==0 then return endState(s,true) end
   local ai=possible[rnd(#possible)]
   for _,col in ipairs(possible) do
    local copy={}
    for yy=1,6 do copy[yy]={};for xx=1,7 do copy[yy][xx]=s.board[yy][xx] end end
    local probe={board=copy}
    c4Drop(probe,col,2)
    if c4Winner(copy)==2 then ai=col;break end
    for yy=1,6 do for xx=1,7 do copy[yy][xx]=s.board[yy][xx] end end
    c4Drop(probe,col,1)
    if c4Winner(copy)==1 then ai=col end
   end
   c4Drop(s,ai,2);s.moves=s.moves+1
   if c4Winner(s.board)==2 then return endState(s) end
   s.score=s.score+10
  end
 end)
-- 18 / TARGET RUSH
add("TARGET","TARGET RUSH","REFLEX","(+)","FAST AIMING CHALLENGE",
 function() return {x=math.floor(W/2),y=math.floor(H/2),tx=rnd(W-18)+9,ty=rnd(H-17)+8,score=0,tick=0,time=360} end,
 function(s)
  hud("TARGET RUSH",s.score,"TIME "..math.ceil(s.time/12).."s","ARROWS AIM  SPACE FIRE")
  frame(5,8,W-8,H-12,T.edge)
  write(s.tx,s.ty,"[X]",C.red)
  write(s.x,s.y,"+",C.lime)
  center(H-3,"TARGET DISTANCE "..(math.abs(s.x-s.tx)+math.abs(s.y-s.ty)),C.lightGray)
 end,
 function(s,k)
  if k==keys.up then s.y=math.max(9,s.y-2)
  elseif k==keys.down then s.y=math.min(H-5,s.y+2)
  elseif k==keys.left then s.x=math.max(6,s.x-2)
  elseif k==keys.right then s.x=math.min(W-6,s.x+2)
  elseif k==keys.space then
   if math.abs(s.x-s.tx)<=2 and math.abs(s.y-s.ty)<=1 then
    s.score=s.score+50;beep(1.7)
    s.tx=rnd(W-18)+9;s.ty=rnd(H-17)+8
   else s.score=math.max(0,s.score-5) end
  end
 end,
 function(s)
  s.time=s.time-1
  if s.time<=0 then endState(s,s.score>=150) end
 end)
-- Console pages.
local entries={}
for _,g in ipairs(games) do entries[#entries+1]=g end
entries[#entries+1]={id="RECORDS",name="HALL OF FAME",category="SYSTEM",icon="TOP",tag="YOUR BEST SCORES",system=true}
entries[#entries+1]={id="SETTINGS",name="SETTINGS",category="SYSTEM",icon="CFG",tag="TUNE YOUR ARCADE",system=true}
entries[#entries+1]={id="HELP",name="HOW TO PLAY",category="SYSTEM",icon="???",tag="CONTROLS / SUPPORT",system=true}
local selected=math.max(1,math.min(#entries,data.selected or 1))
local perPage=6
local columns=3
local function drawCard(index,x,y,w,h)
 local g=entries[index]
 local active=index==selected
 local col=active and T.accent or T.panel
 rect(x,y,w,h,col)
 rect(x,y,w,1,active and T.bright or T.edge)
 if active then frame(x,y,w,h,T.bright) end
 local icon=g.icon or "???"
 center(1,"")
 write(x+math.floor((w-#icon)/2),y+2,icon,active and C.white or T.hot,col)
 write(x+2,y+4,g.name,C.white,col)
 write(x+2,y+5,g.category,C.lightGray,col)
 write(x+2,y+h-2,g.tag:sub(1,w-4),C.white,col)
end
local function splash()
 shell("BOOTING BLACKSITE ARCADE","RETRO GAMING SYSTEM // "..version)
 rect(math.floor(W/2)-21,math.floor(H/2),42,2,C.gray)
 for i=1,42,3 do
  rect(math.floor(W/2)-21,math.floor(H/2),i,2,T.hot)
  sleep(0.03)
 end
 center(math.floor(H/2)+4,"CREATE LINKED CONTROLLER READY",C.lime)
 center(math.floor(H/2)+6,#games.." INSTALLED GAMES",T.bright)
 sleep(0.4)
end
local function drawHome()
 shell("SELECT YOUR EXPERIENCE",#games.." GAMES  /  "..(data.difficulty==1 and "CASUAL" or data.difficulty==2 and "CLASSIC" or "HARDCORE").." MODE")
 local page=math.floor((selected-1)/perPage)
 local first=page*perPage+1
 local cardW=math.floor((W-8)/3)
 local cardH=math.min(10,math.floor((H-12)/2))
 for i=0,5 do
  local idx=first+i
  if entries[idx] then
   local x=3+(i%3)*(cardW+1)
   local y=8+math.floor(i/3)*(cardH+1)
   drawCard(idx,x,y,cardW,cardH)
  end
 end
 local g=entries[selected]
 center(H-3,"< PAGE "..(page+1).." / "..math.ceil(#entries/perPage).." >   "..g.name,T.hot)
 footer("ARROWS BROWSE   SPACE PLAY / OPEN")
end
local function recordsScreen()
 local first=1
 while true do
  shell("HALL OF FAME","PERSISTENT LOCAL RECORDS")
  for i=first,math.min(#games,first+math.min(9,math.floor((H-13)/2))) do
   local g=games[i]
   local y=8+(i-first)*2
   write(math.floor(W/2)-26,y,string.format("%02d  %-19s",i,g.name),i==first and T.hot or C.white)
   write(math.floor(W/2)+5,y,string.format("%6d  %dx",data.records[g.id] or 0,data.played[g.id] or 0),C.yellow)
  end
  footer("UP/DOWN SCROLL   LEFT/SPACE RETURN")
  local e,k=poll()
  if e=="key" then
   if k==keys.left or k==keys.space or k==keys.q then return
   elseif k==keys.down then first=math.min(#games,first+1)
   elseif k==keys.up then first=math.max(1,first-1) end
  end
 end
end
local settingNames={"THEME","DIFFICULTY","MONITOR SCALE","CONTROLLER REPEAT","SOUND","RESET RECORDS","BACK"}
local function settingsScreen()
 local choice=1
 while true do
  shell("SYSTEM SETTINGS","CHANGES SAVE AUTOMATICALLY")
  local values={
   ({"NEON PURPLE","OCEAN BLUE","TOXIC GREEN"})[data.theme],
   ({"CASUAL","CLASSIC","HARDCORE"})[data.difficulty],
   tostring(data.scale),
   string.format("%.2fs",data.repeatDelay),
   data.sound and "ON" or "OFF",
   "HOLD SPACE TO CONFIRM",
   "RETURN TO LIBRARY"
  }
  for i,name in ipairs(settingNames) do
   local y=8+(i-1)*3
   if y<H-2 then
    rect(6,y,W-12,2,i==choice and T.accent or C.gray)
    write(9,y,name,C.white)
    write(math.max(10,W-35),y,values[i] or "",C.yellow)
   end
  end
  footer("UP/DOWN SELECT   LEFT/RIGHT CHANGE   SPACE")
  local e,k=poll()
  if e=="key" then
   if k==keys.up then choice=math.max(1,choice-1)
   elseif k==keys.down then choice=math.min(#settingNames,choice+1)
   elseif k==keys.q or (k==keys.space and choice==7) then return
   elseif k==keys.left or k==keys.right or k==keys.space then
    local dir=k==keys.left and -1 or 1
    if choice==1 then data.theme=(data.theme-1+dir)%3+1;T=themes[data.theme]
    elseif choice==2 then data.difficulty=(data.difficulty-1+dir)%3+1
    elseif choice==3 then
     local scales={0.5,1,1.5}
     local idx=1;for i,v in ipairs(scales) do if v==data.scale then idx=i end end
     data.scale=scales[(idx-1+dir)%#scales+1]
     if mon then mon.setTextScale(data.scale);W,H=term.getSize() end
    elseif choice==4 then data.repeatDelay=math.max(0.05,math.min(0.3,math.floor((data.repeatDelay+dir*0.025)*1000+0.5)/1000))
    elseif choice==5 then data.sound=not data.sound
    elseif choice==6 and k==keys.space then
     notice("RESET RECORDS? ",{"THIS CANNOT BE UNDONE","HOLD SPACE FOR 1.2s TO CONFIRM","LEFT TO CANCEL"})
     while true do
      local e2,k2=poll()
      if e2=="hold" and k2==keys.space then data.records={};data.played={};break
      elseif e2=="key" and (k2==keys.left or k2==keys.q) then break end
     end
    end
    save();beep(1)
   end
  end
 end
end
local function helpScreen()
 local lines={
  "BLACKSITE ARCADE OS "..version.." // "..#games.." GAMES",
  "CREATE LINKED CONTROLLER RECEIVERS:",
  "COMPUTER LEFT    = CONTROLLER LEFT",
  "COMPUTER TOP     = CONTROLLER RIGHT",
  "COMPUTER BOTTOM  = CONTROLLER UP",
  "COMPUTER BACK    = CONTROLLER DOWN",
  "COMPUTER FRONT   = SPACE / ACTION",
  "HOLD FRONT/ACTION 1.2s = PAUSE / EXIT",
  "KEYBOARD: WASD, ARROWS, ENTER, P, Q",
  "MONITOR: ADVANCED 6x3, TEXT SCALE 0.5",
  "HIGH SCORES & SETTINGS AUTO-SAVE",
  "IF A GAME ENDS: SPACE RETRY, LEFT EXIT"
 }
 shell("HOW TO PLAY","HARDWARE / CONTROLS / SUPPORT")
 for i,v in ipairs(lines) do
  local y=8+(i-1)*2
  if y<H-2 then center(y,v,i==1 and T.hot or C.white) end
 end
 footer("SPACE / LEFT RETURN")
 while true do local e,k=poll();if e=="key" and (k==keys.space or k==keys.left or k==keys.q) then return end end
end
local function main()
 splash()
 while true do
  drawHome()
  local e,k=poll()
  if e=="key" then
   local page=math.floor((selected-1)/perPage)
   local column=(selected-1)%columns
   local row=math.floor(((selected-1)%perPage)/columns)
   local candidate=selected
   if k==keys.left then candidate=selected-1
   elseif k==keys.right then candidate=selected+1
   elseif k==keys.up then candidate=selected-columns
   elseif k==keys.down then candidate=selected+columns end
   if candidate~=selected then
    if candidate<1 then candidate=#entries elseif candidate>#entries then candidate=1 end
    selected=candidate;data.selected=selected;save();beep(0.85)
   elseif k==keys.space then
    local g=entries[selected]
    beep(1.4)
    if g.id=="RECORDS" then recordsScreen()
    elseif g.id=="SETTINGS" then settingsScreen()
    elseif g.id=="HELP" then helpScreen()
    else session(g) end
   elseif k==keys.q then return end
  elseif e=="touch" then
   local cardW=math.floor((W-8)/3)
   local cardH=math.min(10,math.floor((H-12)/2))
   for i=0,5 do
    local x=3+(i%3)*(cardW+1)
    local y=8+math.floor(i/3)*(cardH+1)
    if k.x>=x and k.x<x+cardW and k.y>=y and k.y<y+cardH then
     local index=math.floor((selected-1)/perPage)*perPage+i+1
     if entries[index] then
      selected=index;data.selected=selected;save()
      local g=entries[selected]
      if g.id=="RECORDS" then recordsScreen()
      elseif g.id=="SETTINGS" then settingsScreen()
      elseif g.id=="HELP" then helpScreen()
      else session(g) end
     end
    end
   end
  end
 end
end
local ok,err=pcall(main)
term.redirect(native)
term.setBackgroundColor(C.black);term.setTextColor(C.white);term.clear();term.setCursorPos(1,1)
if not ok then print("BLACKSITE ARCADE ERROR:");print(tostring(err)) else print("BLACKSITE ARCADE shutdown.") end
