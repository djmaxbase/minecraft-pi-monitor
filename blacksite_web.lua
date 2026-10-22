-- BLACKSITE -> Uitgeteld-Pi (requires HTTP API enabled on server)
-- Configure URL and token on first launch, saved locally.
local path="blacksite_web_config"
local function readConfig()
 if not fs.exists(path) then return {} end
 local f=fs.open(path,"r");local v=textutils.unserialize(f.readAll());f.close()
 return type(v)=="table" and v or {}
end
local cfg=readConfig()
if not cfg.url then write("HTTPS API URL (e.g. https://domain/api/radar/ingest): ");cfg.url=read() end
if not cfg.token then write("BLACKSITE_RADAR_TOKEN: ");cfg.token=read() end
local f=fs.open(path,"w");f.write(textutils.serialize(cfg));f.close()
local function radar()
 for _,s in ipairs(peripheral.getNames()) do
  if peripheral.hasType(s,"create_radar:monitor") then return peripheral.wrap(s) end
 end
 return peripheral.wrap("create_radar:monitor_0")
end
while true do
 local device=radar()
 if device then
  local ok,data=pcall(function() return device.getTracks() end)
  if ok and type(data)=="table" then
   local tracks={}
   for _,t in pairs(data) do
    if type(t)=="table" and type(t.position)=="table" then
     tracks[#tracks+1]={id=tostring(t.id or t.uuid or ""),name=t.playerName or t.username or t.name or "",category=t.category or "OTHER",entityType=t.entityType or "",position=t.position}
    end
   end
   local okPost,res=pcall(http.post,cfg.url,textutils.serializeJSON({tracks=tracks}),{["Content-Type"]="application/json",["Authorization"]="Bearer "..cfg.token})
   if okPost and res then print("RADAR SYNC "..res.getResponseCode().." / "..#tracks);res.close() else print("Radar sync failed. Check HTTP access/URL.") end
  end
 else print("Radar peripheral unavailable") end
 sleep(5)
end
