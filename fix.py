f = open('static/index.html', encoding='utf-8').read()
old = 'async function send(overrideText) {\n  if (!msg) return;'
new = 'async function send(overrideText) {\n  const msg = overrideText || input.value.trim();\n  if (!msg) return;'
f2 = f.replace(old, new)
if f == f2:
    print('교체 실패 - 이미 수정됐거나 텍스트 불일치')
else:
    open('static/index.html', 'w', encoding='utf-8').write(f2)
    print('완료!')
