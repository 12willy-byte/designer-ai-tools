import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

HTML = r'''<!DOCTYPE html>
<html lang='zh-CN'>
<head>
<meta charset='UTF-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>设计师AI辅助工具</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI','Microsoft YaHei',sans-serif;background:#1a1a2e;color:#e0e0e0;min-height:100vh}
header{background:#16213e;padding:16px 24px;display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #0f3460}
header h1{font-size:20px;color:#e94560}
.container{display:flex;height:calc(100vh - 60px)}
.sidebar{width:380px;background:#16213e;padding:20px;overflow-y:auto;border-right:1px solid #0f3460}
.main{flex:1;display:flex;flex-direction:column}
.toolbar{background:#16213e;padding:12px 20px;display:flex;gap:10px;border-bottom:1px solid #0f3460}
.viewer{flex:1;position:relative;background:#0a0a1a}
.viewer iframe{width:100%;height:100%;border:none}
.status{background:#16213e;padding:10px 20px;font-size:13px;color:#888;border-top:1px solid #0f3460}
h3{font-size:16px;color:#e94560;margin:16px 0 10px}
label{display:block;font-size:13px;color:#aaa;margin:8px 0 4px}
input,select,textarea{width:100%;padding:8px 10px;background:#0f3460;border:1px solid #1a5fa0;color:#fff;border-radius:4px;font-size:14px}
input:focus,select:focus,textarea:focus{outline:none;border-color:#e94560}
textarea{height:80px;resize:vertical}
.room-card{background:#0f3460;border-radius:6px;padding:12px;margin:10px 0}
.room-card .row{display:flex;gap:8px}
.room-card .row>*{flex:1}
.btn{background:#e94560;color:#fff;border:none;padding:10px 16px;border-radius:4px;cursor:pointer;font-size:14px;font-weight:600;transition:all .2s}
.btn:hover{background:#c73650}
.btn:disabled{opacity:.5;cursor:not-allowed}
.btn-sm{padding:6px 12px;font-size:12px}
.btn-out{background:transparent;border:1px solid #e94560;color:#e94560}
.btn-out:hover{background:#e94560;color:#fff}
.budget-table{width:100%;font-size:13px;border-collapse:collapse;margin:10px 0}
.budget-table th,.budget-table td{padding:6px 10px;text-align:left;border-bottom:1px solid #0f3460}
.budget-table th{color:#e94560}
.result-item{margin:6px 0;font-size:13px}
.result-item a{color:#64b5f6}
.progress{background:#0f3460;height:4px;border-radius:2px;margin:10px 0}
.progress-bar{background:#e94560;height:100%;border-radius:2px;width:0%;transition:width .3s}
.flex-row{display:flex;gap:10px;align-items:flex-end}
</style>
</head>
<body>
<header>
<h1>设计师AI辅助自动化工具</h1>
<div>
<button class='btn btn-sm btn-out' onclick='resetAll()'>新建项目</button>
<button class='btn btn-sm' onclick='generateAll()'>一键生成全套</button>
</div>
</header>
<div class='container'>
<div class='sidebar'>
<h3>项目设置</h3>
<label>项目名称</label>
<input id='projectName' value='我的家'>
<label>设计风格</label>
<select id='style'>
<option value='modern'>现代简约</option>
<option value='minimalist'>极简主义</option>
<option value='scandinavian'>北欧风</option>
<option value='luxury'>轻奢</option>
<option value='japanese'>日式</option>
<option value='industrial'>工业风</option>
</select>

<h3>房间配置</h3>
<div id='roomList'></div>
<button class='btn btn-sm btn-out' onclick='addRoom()' style='width:100%;margin-top:8px'>+ 添加房间</button>

<h3>生成结果</h3>
<div id='results'></div>
<div id='budgetDisplay'></div>
</div>

<div class='main'>
<div class='toolbar'>
<button class='btn btn-sm' onclick='loadPreview()'>3D预览</button>
<button class='btn btn-sm btn-out' onclick='loadRendering("preview")'>效果图</button>
<button class='btn btn-sm btn-out' onclick='loadRendering("topdown")'>俯视图</button>
<button class='btn btn-sm btn-out' onclick='loadDrawing("01_floor_plan")'>平面图</button>
</div>
<div class='viewer' id='viewer'>
<iframe id='viewerFrame' src='about:blank'></iframe>
</div>
<div class='status' id='status'>就绪 | 点击"一键生成全套"开始</div>
</div>
</div>

<script>
const DEFAULT_ROOMS = [
  {name:'客厅',type:'living',length_mm:5500,width_mm:4500},
  {name:'主卧',type:'bedroom',length_mm:4200,width_mm:3600},
  {name:'厨房',type:'kitchen',length_mm:3000,width_mm:2400},
];

function init(){
  renderRooms(DEFAULT_ROOMS);
  loadPreview();
}
init();

function addRoom(data){{
  const rooms = getRooms();
  rooms.push(data || {name:'新房间',type:'living',length_mm:4000,width_mm:3500});
  renderRooms(rooms);
}}

function removeRoom(idx){{
  const rooms = getRooms();
  rooms.splice(idx,1);
  renderRooms(rooms);
}}

function getRooms(){{
  const cards = document.querySelectorAll('.room-card');
  const rooms = [];
  cards.forEach(card => {{
    rooms.push({{
      name: card.querySelector('.rn').value,
      type: card.querySelector('.rt').value,
      length_mm: parseInt(card.querySelector('.rl').value)||4000,
      width_mm: parseInt(card.querySelector('.rw').value)||3500,
    }});
  }});
  return rooms;
}}

function renderRooms(rooms){{
  const container = document.getElementById('roomList');
  container.innerHTML = rooms.map((r,i) => 
    <div class='room-card'>
      <div class='row'>
        <input class='rn' value='' placeholder='房间名'>
        <select class='rt'>
          <option value='living' >客厅</option>
          <option value='bedroom' >卧室</option>
          <option value='kitchen' >厨房</option>
          <option value='bathroom' >卫生间</option>
          <option value='dining' >餐厅</option>
          <option value='study' >书房</option>
          <option value='entry' >玄关</option>
        </select>
      </div>
      <div class='row' style='margin-top:6px'>
        <input class='rl' type='number' value='' placeholder='长(mm)'>
        <input class='rw' type='number' value='' placeholder='宽(mm)'>
      </div>
      <button class='btn btn-sm btn-out' style='margin-top:6px' onclick='removeRoom()'>删除</button>
    </div>
  ).join('');
}}

async function generateAll(){{
  const status = document.getElementById('status');
  const progress = document.createElement('div');
  progress.className='progress';
  progress.innerHTML='<div class="progress-bar" id="pbar"></div>';
  document.getElementById('results').prepend(progress);
  
  const rooms = getRooms();
  document.getElementById('status').innerHTML = '<div class="progress"><div class="progress-bar" style="width:10%"></div></div> 生成中...';
  
  try{{
    const resp = await fetch('/api/generate',{{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{
        rooms: rooms,
        style: document.getElementById('style').value,
        name: document.getElementById('projectName').value,
      }})
    }});
    
    if(!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    
    document.getElementById('results').innerHTML = data.files.map(f =>
      <div class='result-item'><a href='/output//' target='_blank' onclick='loadInViewer(event,"/output//")'></a></div>
    ).join('');
    
    if(data.budget){{
      let html = '<h3>预算汇总</h3><table class="budget-table">';
      const s = data.budget.summary;
      for(const [k,v] of Object.entries(s)){{
        html += <tr><td></td><td style="text-align:right"></td></tr>;
      }}
      html += '</table>';
      document.getElementById('budgetDisplay').innerHTML = html;
    }}
    
    document.getElementById('status').textContent = '生成完成!';
    loadPreview();
  }}catch(e){{
    document.getElementById('status').textContent = '错误: ' + e.message;
  }}
}}

function loadPreview(){{
  const frame = document.getElementById('viewerFrame');
  // Try loading the latest preview HTML
  frame.src = '/output/latest/3d_preview.html?' + Date.now();
}}

function loadRendering(type){{
  const frame = document.getElementById('viewerFrame');
  frame.src = '/output/latest/renders/' + type + '.png?' + Date.now();
}}

function loadDrawing(name){{
  const frame = document.getElementById('viewerFrame');
  frame.src = '/output/latest/drawings/' + name + '.svg?' + Date.now();
}}

function loadInViewer(e, path){{
  e.preventDefault();
  document.getElementById('viewerFrame').src = path;
}}

function resetAll(){{
  document.getElementById('results').innerHTML = '';
  document.getElementById('budgetDisplay').innerHTML = '';
  document.getElementById('status').textContent = '就绪';
  renderRooms(DEFAULT_ROOMS);
}}
</script>
</body>
</html>
'''

def serve_web(output_dir):
    \"\"\"Save the web app to the project.\"\"\"
    web_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'web')
    os.makedirs(web_dir, exist_ok=True)
    path = os.path.join(web_dir, 'app.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(HTML)
    return path

if __name__ == '__main__':
    p = serve_web('output')
    print(f'Web app: {p}')

print('web_app ready')
