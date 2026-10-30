-- Offline census of the loaded format. No declarations are injected before it.
local function hex(s)
  return (s:gsub('.', function(c) return string.format('%02x', string.byte(c)) end))
end
local names = {}
for _, name in pairs(tex.hashtokens()) do
  assert(type(name) == 'string', 'Unexpected hashtokens value type: ' .. type(name))
  names[#names + 1] = name
end
table.sort(names)
local queries, tokens = {}, {}
for _, name in ipairs(names) do
  local t = token.create(name)
  tokens[name] = t
  if t then
    queries[#queries + 1] = token.new(123, 1)
    queries[#queries + 1] = token.create('meaning')
    queries[#queries + 1] = t
    queries[#queries + 1] = token.new(125, 2)
  end
end
-- One input frame: repeatedly putting an argument back from inside the same Lua
-- call leaves exhausted TeX input frames awaiting return to the main loop.
token.put_next(queries)
local output = assert(io.open('lua-census.tsv', 'wb'))
for _, name in ipairs(names) do
  local t = tokens[name]
  local meaning = ''
  if t then
    -- get_meaning supplies only macro parameter/replacement text, omitting
    -- flags and non-macro meanings. Ask the TeX primitive for the full display.
    meaning = token.scan_argument(true)
  end
  output:write(hex(name), '\t', t and t.cmdname or 'unavailable_token', '\t', hex(meaning), '\n')
end
output:close()
local meta = assert(io.open('lua-meta.tsv', 'wb'))
meta:write('version\t', tostring(status.luatex_version), '\n')
meta:write('revision\t', tostring(status.luatex_revision), '\n')
meta:write('format\t', hex(token.get_macro('fmtversion') or ''), '\n')
meta:write('expl3\t', hex(token.get_macro('ExplFileDate') or ''), '\n')
meta:write('hash_entries\t', tostring(#names), '\n')
meta:close()
