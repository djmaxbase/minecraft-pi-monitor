-- BLACKSITE ARCADE 1.0 - CC:Tweaked Advanced Computer
local native=term.current()
local monitor=peripheral.find("monitor")
if monitor then
 monitor.setTextScale(0.5)
 term.redirect(monitor)
else
 print("No monitor detected: using computer screen")
end
local W,H=term.getSize()
if not term.isColor() then term.redirect(native);print("Color display required");return end
local C=colors
local scores={}
local scoreFile="arcade_scores"
if fs.exists(scoreFile) then local f=fs.open(scoreFile,"r");scores=textutils.unserialize(f.readAll()) or {};f.close() end
local function save() local f=fs.open(scoreFile,"w");f.write(textutils.serialize(scores));f.close() end
local function best(name,score) if score>(scores[name] or 0) then scores[name]=score;save() end end
local function center(y,s,col) term.setTextColor(col or C.white);term.setCursorPos(math.max(1,math.floor((W-#s)/2)+1),y);term.write(s) end
local function clear(bg) term.setBackgroundColor(bg or C.black);term.setTextColor(C.white);term.clear();term.setCursorPos(1,1) end
local function bar(title) clear(C.black);term.setBackgroundColor(C.blue);term.setTextColor(C.white);term.setCursorPos(1,1);term.clearLine();center(1," BLACKSITE ARCADE | "..title);term.setBackgroundColor(C.black) end
local function footer(s) term.setBackgroundColor(C.gray);term.setTextColor(C.white);term.setCursorPos(1,H);term.clearLine();center(H,s);term.setBackgroundColor(C.black) end
local function waitKey() while true do local e,k=os.pullEvent();if e=="key" then return k end end end
local function gameOver(name,score) best(name,score);bar("GAME OVER");center(math.floor(H/2)-2,name,C.orange);center(math.floor(H/2),"SCORE "..score,C.lime);center(math.floor(H/2)+2,"BEST "..(scores[name] or 0),C.yellow);footer("ENTER = MENU");while waitKey()~=keys.enter do end end
local function snake()
 local gw,gh=math.min(W-4,math.max(24,W-8)),math.min(H-7,math.max(14,H-8))
 local x0,y0=math.floor((W-gw)/2)+1,3
 local snake={{x=math.floor(gw/2),y=math.floor(gh/2)}}
 local dx,dy=1,0;local food={x=2,y=2};local score=0;local alive=true
 local function spawn()
  for _=1,150 do local x,y=math.random(1,gw),math.random(1,gh);local ok=true
   for _,p in ipairs(snake) do if p.x==x and p.y==y then ok=false;break end end
   if ok then food={x=x,y=y};return end
  end
 end
 spawn()
 local timer=os.startTimer(.17)
 while alive do
  bar("SNAKE");center(2,"SCORE "..score.."   BEST "..(scores.SNAKE or 0),C.lime)
  for y=1,gh do term.setCursorPos(x0,y0+y-1);term.setBackgroundColor(C.gray);term.write(string.rep(" ",gw)) end
  term.setBackgroundColor(C.red);term.setCursorPos(x0+food.x-1,y0+food.y-1);term.write(" ")
  for i,p in ipairs(snake) do term.setBackgroundColor(i==1 and C.lime or C.green);term.setCursorPos(x0+p.x-1,y0+p.y-1);term.write(" ") end
  term.setBackgroundColor(C.black);footer("ARROWS / WASD   Q = EXIT")
  local e,a=os.pullEvent()
  if e=="key" then
   if a==keys.q then return end
   if (a==keys.up or a==keys.w) and dy~=1 then dx,dy=0,-1
   elseif (a==keys.down or a==keys.s) and dy~=-1 then dx,dy=0,1
   elseif (a==keys.left or a==keys.a) and dx~=1 then dx,dy=-1,0
   elseif (a==keys.right or a==keys.d) and dx~=-1 then dx,dy=1,0 end
  elseif e=="timer" and a==timer then
   local h=snake[1];local nx,ny=h.x+dx,h.y+dy
   if nx<1 or nx>gw or ny<1 or ny>gh then alive=false;break end
   local eat=nx==food.x and ny==food.y
   for i,p in ipairs(snake) do if (eat or i<#snake) and p.x==nx and p.y==ny then alive=false end end
   if not alive then break end
   table.insert(snake,1,{x=nx,y=ny});if eat then score=score+10;spawn() else table.remove(snake) end
   timer=os.startTimer(math.max(.075,.17-score/3000))
  end
 end
 gameOver("SNAKE",score)
end
local function pong()
 local gw,gh=W-4,H-6;local x0,y0=3,3
 local py=math.floor(gh/2);local ai=py;local bx,by=math.floor(gw/2),math.floor(gh/2)
 local vx,vy=1,1;local score=0;local timer=os.startTimer(.10)
 while true do
  bar("PONG");center(2,"YOU "..score.."  -  "..(scores.PONG or 0).." BEST",C.lime)
  for y=1,gh do term.setCursorPos(x0,y0+y-1);term.setBackgroundColor(C.black);term.write(string.rep(" ",gw)) end
  for d=-1,1 do for _,p in ipairs({{1,py,C.lime},{gw,ai,C.red}}) do local y=p[2]+d;if y>=1 and y<=gh then term.setCursorPos(x0+p[1]-1,y0+y-1);term.setBackgroundColor(p[3]);term.write(" ") end end end
  term.setCursorPos(x0+bx-1,y0+by-1);term.setBackgroundColor(C.white);term.write(" ");term.setBackgroundColor(C.black)
  footer("UP / DOWN or W / S   Q = EXIT")
  local e,k=os.pullEvent()
  if e=="key" then if k==keys.q then best("PONG",score);return elseif k==keys.up or k==keys.w then py=math.max(2,py-2) elseif k==keys.down or k==keys.s then py=math.min(gh-1,py+2) end
  elseif e=="timer" and k==timer then
   bx=bx+vx;by=by+vy
   if by<=1 then by=1;vy=1 elseif by>=gh then by=gh;vy=-1 end
   if bx<=2 then if math.abs(by-py)<=1 then bx=2;vx=1;score=score+1 else break end end
   if bx>=gw-1 then if math.abs(by-ai)<=1 then bx=gw-1;vx=-1 else bx=math.floor(gw/2);by=math.floor(gh/2);vx=-1 end end
   if ai<by then ai=math.min(gh-1,ai+1) elseif ai>by then ai=math.max(2,ai-1) end
   timer=os.startTimer(.10)
  end
 end
 gameOver("PONG",score)
end
local function blocks()
 local bw,bh=10,math.min(20,H-6);local x0,y0=math.floor((W-bw*2)/2)+1,3
 local board={};for y=1,bh do board[y]={} end
 local shapes={{{0,0},{1,0},{0,1},{1,1}},{{0,0},{1,0},{2,0},{3,0}},{{0,0},{1,0},{2,0},{1,1}},{{0,0},{1,0},{1,1},{2,1}},{{1,0},{2,0},{0,1},{1,1}},{{0,0},{0,1},{1,1},{2,1}},{{2,0},{0,1},{1,1},{2,1}}}
 local palette={C.yellow,C.cyan,C.purple,C.red,C.lime,C.blue,C.orange}
 local piece,x,y,kind,score=nil,4,1,1,0
 local function fits(s,px,py) for _,p in ipairs(s) do local xx,yy=px+p[1],py+p[2];if xx<1 or xx>bw or yy>bh or (yy>=1 and board[yy][xx]) then return false end end return true end
 local function newPiece() kind=math.random(#shapes);piece={};for _,p in ipairs(shapes[kind]) do piece[#piece+1]={p[1],p[2]} end;x=4;y=1;return fits(piece,x,y) end
 local function lock()
  for _,p in ipairs(piece) do local xx,yy=x+p[1],y+p[2];if yy>=1 and yy<=bh then board[yy][xx]=palette[kind] end end
  local row=bh;while row>=1 do local full=true;for col=1,bw do if not board[row][col] then full=false end end
   if full then table.remove(board,row);table.insert(board,1,{});score=score+100 else row=row-1 end
  end
  return newPiece()
 end
 local function down() if fits(piece,x,y+1) then y=y+1;return true else return lock() end end
 local function rotate() local rotated={};for _,p in ipairs(piece) do rotated[#rotated+1]={-p[2],p[1]} end;local minx,miny=99,99;for _,p in ipairs(rotated) do minx=math.min(minx,p[1]);miny=math.min(miny,p[2]) end;for _,p in ipairs(rotated) do p[1]=p[1]-minx;p[2]=p[2]-miny end;if fits(rotated,x,y) then piece=rotated end end
 newPiece();local timer=os.startTimer(.6);local alive=true
 while alive do
  bar("BLOCK DROP");center(2,"SCORE "..score.."   BEST "..(scores.BLOCKS or 0),C.lime)
  for yy=1,bh do for xx=1,bw do term.setCursorPos(x0+(xx-1)*2,y0+yy-1);term.setBackgroundColor(board[yy][xx] or C.gray);term.write("  ") end end
  for _,p in ipairs(piece) do local xx,yy=x+p[1],y+p[2];if yy>=1 and yy<=bh then term.setCursorPos(x0+(xx-1)*2,y0+yy-1);term.setBackgroundColor(palette[kind]);term.write("  ") end end
  term.setBackgroundColor(C.black);footer("LEFT/RIGHT MOVE  UP ROTATE  DOWN DROP  Q EXIT")
  local e,k=os.pullEvent()
  if e=="key" then
   if k==keys.q then best("BLOCKS",score);return
   elseif (k==keys.left or k==keys.a) and fits(piece,x-1,y) then x=x-1
   elseif (k==keys.right or k==keys.d) and fits(piece,x+1,y) then x=x+1
   elseif k==keys.up or k==keys.w then rotate()
   elseif k==keys.down or k==keys.s then alive=down() end
  elseif e=="timer" and k==timer then alive=down();timer=os.startTimer(math.max(.12,.6-score/5000)) end
 end
 gameOver("BLOCKS",score)
end
local games={{"SNAKE","Classic survival",snake},{"PONG","Beat the CPU",pong},{"BLOCK DROP","Falling block puzzle",blocks}}
local selected=1
while true do
 bar("HOME");center(3,"B L A C K S I T E",C.cyan);center(4,"A R C A D E   O S",C.lime)
 for i,g in ipairs(games) do local yy=6+i*3;if yy<H-1 then term.setBackgroundColor(i==selected and C.blue or C.gray);term.setTextColor(C.white);term.setCursorPos(4,yy);term.write(string.rep(" ",W-7));term.setCursorPos(5,yy);term.write((i==selected and "> " or "  ")..g[1]);term.setBackgroundColor(C.black);term.setTextColor(C.lightGray);term.setCursorPos(6,yy+1);term.write(g[2].."  |  BEST "..(scores[g[1]=="BLOCK DROP" and "BLOCKS" or g[1]] or 0)) end end
 footer("UP/DOWN SELECT  ENTER PLAY  Q SHUT DOWN")
 local k=waitKey()
 if k==keys.up then selected=selected==1 and #games or selected-1
 elseif k==keys.down then selected=selected==#games and 1 or selected+1
 elseif k==keys.enter then local ok,err=pcall(games[selected][3]);if not ok then bar("ERROR");center(5,tostring(err):sub(1,W-2),C.red);sleep(3) end
 elseif k==keys.q then clear();term.redirect(native);print("BLACKSITE Arcade shutdown");return end
end
