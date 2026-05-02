"""
Three.js 3D Template Library (Oturum 25.40p — Neo direktif)
=============================================================

Vakası:
- 1 May 20:04/20:09/20:26: Neo "güneş sistemimizin galaksimiz içinde 3D hareket,
  great attractor'a doğru" — 3 kez aynı mesaj, bot statik text cevap verdi.
- 29 Nis 23:01: Neo "informatik konuyla ilgili 3D animasyonlar olsa konuyla
  ilgili anlık üretseniz çok daha etkili."

Çözüm: Önyüklü Three.js HTML template'leri + dinamik prompt-based üretim.
Bot "make_render_link" tool ile bu template'leri çağırır → HTML render endpoint'e
yazılır → kullanıcıya kalıcı link.

Mevcut templates:
- solar_system_great_attractor() — Güneş sistemi + galaksi + GA vektörü
- atom_model(element) — Bohr atom modeli (H, He, Li, ...)
- hucre_model(tip) — Bitki/hayvan hücresi organel rotasyon
- molekul_3d(formula) — Basit molekül (H2O, CO2, CH4, NH3)

Kullanım:
  from three_templates import solar_system_great_attractor, atom_model
  html = solar_system_great_attractor()
  # → bot make_render_link(html, title="Güneş Sistemi") çağırır
"""
from __future__ import annotations


# ════════════════════════════════════════════════════════════════════
# COMMON HTML SHELL — minimum boyut için tek file
# ════════════════════════════════════════════════════════════════════

_HTML_SHELL = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  body{{margin:0;background:#000;font-family:-apple-system,system-ui,sans-serif;color:#fff;overflow:hidden}}
  #info{{position:fixed;top:10px;left:10px;background:rgba(15,23,42,0.85);padding:10px 14px;border-radius:8px;font-size:13px;max-width:280px;border:1px solid rgba(199,111,62,0.3)}}
  #info h2{{margin:0 0 6px;font-size:14px;color:#C76F3E}}
  #info p{{margin:4px 0;line-height:1.4;font-size:12px}}
  #info .key{{color:#A78BFA;font-weight:600}}
  #controls{{position:fixed;bottom:10px;left:50%;transform:translateX(-50%);background:rgba(15,23,42,0.85);padding:8px 16px;border-radius:8px;font-size:11px;color:#999;border:1px solid rgba(199,111,62,0.2)}}
  canvas{{display:block}}
  @media(max-width:600px){{#info{{font-size:11px;max-width:200px}}}}
</style>
</head>
<body>
<div id="info">{info}</div>
<div id="controls">🖱️ Sürükle = döndür · Scroll = zoom · 📱 Dokun = döndür/yakınlaştır</div>
<script src="https://cdn.jsdelivr.net/npm/three@0.160/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.160/examples/js/controls/OrbitControls.js"></script>
<script>
{js}
</script>
</body>
</html>
"""


# ════════════════════════════════════════════════════════════════════
# 1. SOLAR SYSTEM + GREAT ATTRACTOR (Neo direktif #1)
# ════════════════════════════════════════════════════════════════════

def solar_system_great_attractor() -> str:
    """
    Güneş sistemi (8 gezegen + ay + asteroit) + galaksi merkezi etrafında
    spiral hareket + Great Attractor vektörü.

    Fizik:
    - Gezegenler güneş etrafında orbital (Kepler)
    - Güneş kendi yörünge düzleminde + galaksi merkezi etrafında
    - Tüm Samanyolu Great Attractor'a doğru ~600 km/s hareket

    Returns: tam HTML (Three.js + OrbitControls + animation)
    """
    info = """<h2>🌌 Güneş Sistemi & Great Attractor</h2>
<p>Güneş sistemimiz galaksimizin merkezi etrafında dönerken aynı zamanda
<span class="key">Great Attractor</span>'a doğru ~600 km/s hızla ilerliyor.</p>
<p><span class="key">Kırmızı vektör</span>: GA hareket yönü</p>
<p><span class="key">Mavi spiral</span>: Galaksi yörüngesi</p>
<p>Hız: <span class="key">~220 km/s</span> (galaksi)</p>"""

    js = """
const scene=new THREE.Scene();
scene.background=new THREE.Color(0x000005);
const camera=new THREE.PerspectiveCamera(60,innerWidth/innerHeight,0.1,5000);
camera.position.set(80,60,120);
const renderer=new THREE.WebGLRenderer({antialias:true});
renderer.setSize(innerWidth,innerHeight);
document.body.appendChild(renderer.domElement);
const ctrl=new THREE.OrbitControls(camera,renderer.domElement);
ctrl.enableDamping=true;ctrl.dampingFactor=0.05;
addEventListener('resize',()=>{camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight);});

// Stars (galaksi arka plan)
const sg=new THREE.BufferGeometry();
const sp=[];for(let i=0;i<3000;i++){sp.push((Math.random()-0.5)*4000,(Math.random()-0.5)*4000,(Math.random()-0.5)*4000);}
sg.setAttribute('position',new THREE.Float32BufferAttribute(sp,3));
scene.add(new THREE.Points(sg,new THREE.PointsMaterial({color:0xffffff,size:1,transparent:true,opacity:0.8})));

// Galaksi merkezi (Sgr A*)
const galaxy=new THREE.Mesh(new THREE.SphereGeometry(8,32,32),new THREE.MeshBasicMaterial({color:0xff6600,transparent:true,opacity:0.7}));
galaxy.position.set(-300,0,0);
scene.add(galaxy);
scene.add(new THREE.Mesh(new THREE.RingGeometry(15,80,64),new THREE.MeshBasicMaterial({color:0x6699ff,side:THREE.DoubleSide,transparent:true,opacity:0.15}))).position.copy(galaxy.position);

// Solar system grup (galaksi yörüngesinde döner)
const solar=new THREE.Group();
scene.add(solar);

// Güneş
const sun=new THREE.Mesh(new THREE.SphereGeometry(3,32,32),new THREE.MeshBasicMaterial({color:0xffdd00}));
solar.add(sun);
const sunLight=new THREE.PointLight(0xffffff,2,500);
solar.add(sunLight);
scene.add(new THREE.AmbientLight(0x222244,0.3));

// 8 gezegen
const planets=[
{n:'Merkür',c:0x8b8680,r:0.4,d:5,s:0.04},
{n:'Venüs',c:0xeec07c,r:0.7,d:7,s:0.03},
{n:'Dünya',c:0x4488ee,r:0.75,d:9,s:0.025},
{n:'Mars',c:0xcc4422,r:0.5,d:12,s:0.02},
{n:'Jüpiter',c:0xd4a373,r:1.8,d:18,s:0.012},
{n:'Satürn',c:0xe6c896,r:1.6,d:24,s:0.009},
{n:'Uranüs',c:0x88ccdd,r:1.1,d:30,s:0.007},
{n:'Neptün',c:0x4477cc,r:1.0,d:36,s:0.005}
];
const meshes=[];
planets.forEach(p=>{
  const m=new THREE.Mesh(new THREE.SphereGeometry(p.r,16,16),new THREE.MeshLambertMaterial({color:p.c}));
  m.userData={d:p.d,s:p.s,a:Math.random()*Math.PI*2};
  solar.add(m);
  // Yörünge çizgisi
  const og=new THREE.RingGeometry(p.d-0.05,p.d+0.05,64);
  const ol=new THREE.Mesh(og,new THREE.MeshBasicMaterial({color:0x333366,side:THREE.DoubleSide,transparent:true,opacity:0.4}));
  ol.rotation.x=Math.PI/2;
  solar.add(ol);
  meshes.push(m);
});

// Satürn halkası
const ring=new THREE.Mesh(new THREE.RingGeometry(2.0,2.8,32),new THREE.MeshBasicMaterial({color:0xccaa66,side:THREE.DoubleSide,transparent:true,opacity:0.7}));
ring.rotation.x=Math.PI/2.5;
meshes[5].add(ring);

// Great Attractor vektörü (kırmızı ok)
const arrowDir=new THREE.Vector3(1,0.3,0.4).normalize();
const arrow=new THREE.ArrowHelper(arrowDir,new THREE.Vector3(0,0,0),100,0xff3344,15,8);
solar.add(arrow);

// Galaksi spiral yörünge ipucu
const sg2=new THREE.BufferGeometry();
const sp2=[];const cx=-300,cy=0,cz=0,R=300;
for(let i=0;i<400;i++){const t=i*0.04;sp2.push(cx+R*Math.cos(t),cy+t*0.5,cz+R*Math.sin(t));}
sg2.setAttribute('position',new THREE.Float32BufferAttribute(sp2,3));
scene.add(new THREE.Line(sg2,new THREE.LineBasicMaterial({color:0x4488ff,transparent:true,opacity:0.4})));

// Animasyon
let galaxyAngle=0,gaShift=0;
function animate(){
  requestAnimationFrame(animate);
  // Gezegenler güneş etrafında
  meshes.forEach(m=>{m.userData.a+=m.userData.s;m.position.set(Math.cos(m.userData.a)*m.userData.d,0,Math.sin(m.userData.a)*m.userData.d);m.rotation.y+=0.02;});
  sun.rotation.y+=0.005;
  // Solar system galaksi etrafında yavaş yörünge + GA'ya kayma
  galaxyAngle+=0.0008;gaShift+=0.05;
  solar.position.set(-300+300*Math.cos(galaxyAngle)+gaShift*arrowDir.x*0.001,gaShift*arrowDir.y*0.001,300*Math.sin(galaxyAngle)+gaShift*arrowDir.z*0.001);
  galaxy.rotation.y+=0.003;
  ctrl.update();
  renderer.render(scene,camera);
}
animate();
"""
    return _HTML_SHELL.format(title="Güneş Sistemi & Great Attractor", info=info, js=js)


# ════════════════════════════════════════════════════════════════════
# 2. ATOM MODEL (Bohr) — Element bazlı
# ════════════════════════════════════════════════════════════════════

def atom_model(element: str = "H", proton: int = 1, neutron: int = 0,
               electron_shells: list = None) -> str:
    """
    Bohr atom modeli — element bazlı (H, He, Li, C, O, ...)

    Args:
        element: sembol (H/He/Li/Be/B/C/N/O/F/Ne...)
        proton: proton sayısı (=atom numarası)
        neutron: nötron sayısı
        electron_shells: katman elektron dağılımı [2, 8, ...] None ise otomatik
    """
    if electron_shells is None:
        # Otomatik: 1. katman max 2, 2. max 8, 3. max 8 (basit)
        e = proton
        electron_shells = []
        for max_e in [2, 8, 8, 18]:
            if e <= 0:
                break
            n = min(e, max_e)
            electron_shells.append(n)
            e -= n

    shells_js = str(electron_shells).replace("'", "")

    info = f"""<h2>⚛️ {element} Atomu</h2>
<p>Proton: <span class="key">{proton}</span> | Nötron: <span class="key">{neutron}</span></p>
<p>Elektron katmanları: <span class="key">{electron_shells}</span></p>
<p>Çekirdek: <span class="key">kırmızı (proton)</span> + <span class="key">gri (nötron)</span></p>
<p>Elektronlar yörüngede dolanır.</p>"""

    js = f"""
const scene=new THREE.Scene();scene.background=new THREE.Color(0x000010);
const camera=new THREE.PerspectiveCamera(60,innerWidth/innerHeight,0.1,1000);
camera.position.set(0,5,15);
const renderer=new THREE.WebGLRenderer({{antialias:true}});renderer.setSize(innerWidth,innerHeight);document.body.appendChild(renderer.domElement);
const ctrl=new THREE.OrbitControls(camera,renderer.domElement);ctrl.enableDamping=true;
addEventListener('resize',()=>{{camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight);}});
scene.add(new THREE.AmbientLight(0xffffff,0.6));
const pl=new THREE.PointLight(0xffffff,1,100);pl.position.set(0,0,0);scene.add(pl);

// Çekirdek (proton+nötron mix)
const nucleus=new THREE.Group();
const np={proton+neutron};
const protonCount={proton};
for(let i=0;i<np;i++){{
  const r=0.4;
  const isProton=i<protonCount;
  const m=new THREE.Mesh(new THREE.SphereGeometry(r,16,16),new THREE.MeshLambertMaterial({{color:isProton?0xff3344:0xaaaaaa}}));
  const t=Math.random()*Math.PI*2,p=Math.random()*Math.PI;
  m.position.set(0.6*Math.sin(p)*Math.cos(t),0.6*Math.sin(p)*Math.sin(t),0.6*Math.cos(p));
  nucleus.add(m);
}}
scene.add(nucleus);

// Elektron katmanları
const shells={shells_js};
const electrons=[];
shells.forEach((n,k)=>{{
  const radius=2.5+k*1.8;
  // Yörünge çizgisi
  const og=new THREE.RingGeometry(radius-0.02,radius+0.02,64);
  const om=new THREE.MeshBasicMaterial({{color:0x4488cc,side:THREE.DoubleSide,transparent:true,opacity:0.4}});
  const orbit=new THREE.Mesh(og,om);orbit.rotation.x=Math.PI/2 + k*0.3;
  scene.add(orbit);
  // Elektronlar
  for(let i=0;i<n;i++){{
    const angle=(i/n)*Math.PI*2;
    const e=new THREE.Mesh(new THREE.SphereGeometry(0.18,12,12),new THREE.MeshLambertMaterial({{color:0x44aaff,emissive:0x002244}}));
    e.userData={{r:radius,a:angle,s:0.02-k*0.003,tilt:k*0.3}};
    scene.add(e);electrons.push(e);
  }}
}});

function animate(){{
  requestAnimationFrame(animate);
  electrons.forEach(e=>{{
    e.userData.a+=e.userData.s;
    const x=e.userData.r*Math.cos(e.userData.a);
    const z=e.userData.r*Math.sin(e.userData.a);
    e.position.set(x*Math.cos(e.userData.tilt),x*Math.sin(e.userData.tilt),z);
  }});
  nucleus.rotation.y+=0.005;
  ctrl.update();renderer.render(scene,camera);
}}
animate();
"""
    return _HTML_SHELL.format(title=f"{element} Atomu - Bohr Modeli", info=info, js=js)


# ════════════════════════════════════════════════════════════════════
# 3. HÜCRE MODELİ (organeller)
# ════════════════════════════════════════════════════════════════════

def hucre_model(tip: str = "hayvan") -> str:
    """Bitki veya hayvan hücresi — temel organeller görünür."""
    bitki = tip.lower() == "bitki"
    organeller_text = "Çekirdek + Mitokondri + Endoplazmik Retikulum + Golgi + Lizozom"
    if bitki:
        organeller_text += " + Kloroplast + Vakuol + Hücre Duvarı"

    info = f"""<h2>🔬 {tip.title()} Hücresi</h2>
<p>{organeller_text}</p>
<p><span class="key">Sürükle</span>: hücreyi döndür</p>
<p>Renk kodları:</p>
<p>🔵 Çekirdek | 🟠 Mitokondri | 🟢 Kloroplast | 🟣 Golgi</p>"""

    bitki_js = "true" if bitki else "false"
    js = f"""
const scene=new THREE.Scene();scene.background=new THREE.Color(0x001020);
const camera=new THREE.PerspectiveCamera(50,innerWidth/innerHeight,0.1,1000);camera.position.set(0,5,18);
const renderer=new THREE.WebGLRenderer({{antialias:true,alpha:true}});renderer.setSize(innerWidth,innerHeight);document.body.appendChild(renderer.domElement);
const ctrl=new THREE.OrbitControls(camera,renderer.domElement);ctrl.enableDamping=true;
addEventListener('resize',()=>{{camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight);}});
scene.add(new THREE.AmbientLight(0xffffff,0.5));
const dl=new THREE.DirectionalLight(0xffffff,0.8);dl.position.set(10,10,10);scene.add(dl);

const isBitki={bitki_js};
// Hücre zarı (yumuşak küre)
const cellGeo=isBitki?new THREE.BoxGeometry(10,10,10):new THREE.SphereGeometry(6,32,32);
const cell=new THREE.Mesh(cellGeo,new THREE.MeshPhongMaterial({{color:isBitki?0x88dd44:0xcc88aa,transparent:true,opacity:0.18,wireframe:false}}));
scene.add(cell);

// Çekirdek (mavi)
const nuc=new THREE.Mesh(new THREE.SphereGeometry(1.6,32,32),new THREE.MeshPhongMaterial({{color:0x3366cc,emissive:0x112244}}));
scene.add(nuc);

// Mitokondri (turuncu, çoklu)
for(let i=0;i<5;i++){{
  const m=new THREE.Mesh(new THREE.CapsuleGeometry(0.35,0.8,8,16),new THREE.MeshPhongMaterial({{color:0xee7733,emissive:0x331100}}));
  const a=i*1.2,r=2.8;
  m.position.set(Math.cos(a)*r,Math.sin(a*1.2)*1.5,Math.sin(a)*r);
  m.rotation.set(Math.random(),Math.random(),Math.random());
  scene.add(m);
}}

// ER + Golgi (mor küme)
for(let i=0;i<3;i++){{
  const g=new THREE.Mesh(new THREE.TorusGeometry(0.5,0.15,8,24),new THREE.MeshPhongMaterial({{color:0x9966cc}}));
  g.position.set(-2+i*0.6,1.5,0.5);g.rotation.x=Math.PI/3;
  scene.add(g);
}}

// Kloroplast (yeşil, sadece bitki)
if(isBitki){{
  for(let i=0;i<6;i++){{
    const k=new THREE.Mesh(new THREE.EllipseCurve?new THREE.SphereGeometry(0.5,16,16):new THREE.SphereGeometry(0.5,16,16),new THREE.MeshPhongMaterial({{color:0x55cc44,emissive:0x113311}}));
    k.scale.set(1,0.5,1.4);
    const a=i*1.0+0.3,r=2.5;
    k.position.set(Math.cos(a)*r,Math.cos(a*0.8)*1,Math.sin(a)*r);
    scene.add(k);
  }}
  // Vakuol (büyük şeffaf merkez)
  const v=new THREE.Mesh(new THREE.SphereGeometry(2.5,32,32),new THREE.MeshPhongMaterial({{color:0xaaffff,transparent:true,opacity:0.25}}));
  v.position.set(2,-1,0);scene.add(v);
}}

// Lizozomlar (küçük sarı)
for(let i=0;i<8;i++){{
  const l=new THREE.Mesh(new THREE.SphereGeometry(0.2,12,12),new THREE.MeshPhongMaterial({{color:0xffdd44,emissive:0x332200}}));
  const t=Math.random()*Math.PI*2,p=Math.random()*Math.PI,r=2.2+Math.random()*1.5;
  l.position.set(r*Math.sin(p)*Math.cos(t),r*Math.sin(p)*Math.sin(t),r*Math.cos(p));
  scene.add(l);
}}

function animate(){{
  requestAnimationFrame(animate);
  cell.rotation.y+=0.001;nuc.rotation.y+=0.005;
  ctrl.update();renderer.render(scene,camera);
}}
animate();
"""
    return _HTML_SHELL.format(title=f"{tip.title()} Hücresi - 3D Model", info=info, js=js)


# ════════════════════════════════════════════════════════════════════
# 4. MOLEKÜL 3D — basit moleküller
# ════════════════════════════════════════════════════════════════════

def molekul_3d(formula: str = "H2O") -> str:
    """
    Basit molekül 3D modeli (H2O, CO2, CH4, NH3, O2, N2)

    Atom renkleri:
    - H: beyaz, C: siyah, O: kırmızı, N: mavi
    """
    formula = formula.upper().strip()

    # Önyüklü konfigürasyonlar
    molekuller = {
        "H2O": {
            "atomlar": [
                {"e": "O", "c": 0xee2222, "r": 0.7, "p": [0, 0, 0]},
                {"e": "H", "c": 0xffffff, "r": 0.4, "p": [0.96, 0.4, 0]},
                {"e": "H", "c": 0xffffff, "r": 0.4, "p": [-0.96, 0.4, 0]},
            ],
            "baglar": [(0, 1), (0, 2)],
            "isim": "Su (H₂O)",
            "aci": "104.5°"
        },
        "CO2": {
            "atomlar": [
                {"e": "C", "c": 0x222222, "r": 0.5, "p": [0, 0, 0]},
                {"e": "O", "c": 0xee2222, "r": 0.7, "p": [1.5, 0, 0]},
                {"e": "O", "c": 0xee2222, "r": 0.7, "p": [-1.5, 0, 0]},
            ],
            "baglar": [(0, 1), (0, 2)],
            "isim": "Karbondioksit (CO₂)",
            "aci": "180° (lineer)"
        },
        "CH4": {
            "atomlar": [
                {"e": "C", "c": 0x222222, "r": 0.5, "p": [0, 0, 0]},
                {"e": "H", "c": 0xffffff, "r": 0.35, "p": [0.7, 0.7, 0.7]},
                {"e": "H", "c": 0xffffff, "r": 0.35, "p": [-0.7, -0.7, 0.7]},
                {"e": "H", "c": 0xffffff, "r": 0.35, "p": [-0.7, 0.7, -0.7]},
                {"e": "H", "c": 0xffffff, "r": 0.35, "p": [0.7, -0.7, -0.7]},
            ],
            "baglar": [(0, 1), (0, 2), (0, 3), (0, 4)],
            "isim": "Metan (CH₄)",
            "aci": "109.5° (tetrahedral)"
        },
        "NH3": {
            "atomlar": [
                {"e": "N", "c": 0x4477cc, "r": 0.6, "p": [0, 0.3, 0]},
                {"e": "H", "c": 0xffffff, "r": 0.35, "p": [0.94, -0.27, 0]},
                {"e": "H", "c": 0xffffff, "r": 0.35, "p": [-0.47, -0.27, 0.81]},
                {"e": "H", "c": 0xffffff, "r": 0.35, "p": [-0.47, -0.27, -0.81]},
            ],
            "baglar": [(0, 1), (0, 2), (0, 3)],
            "isim": "Amonyak (NH₃)",
            "aci": "107° (piramidal)"
        },
    }

    if formula not in molekuller:
        formula = "H2O"  # default

    mol = molekuller[formula]

    info = f"""<h2>🧪 {mol['isim']}</h2>
<p>Bağ açısı: <span class="key">{mol['aci']}</span></p>
<p>Atom sayısı: <span class="key">{len(mol['atomlar'])}</span></p>
<p>Renk kodları:</p>
<p>⚪ H · ⚫ C · 🔴 O · 🔵 N</p>"""

    atomlar_js = ",".join([
        f"{{e:'{a['e']}',c:0x{a['c']:06x},r:{a['r']},p:[{a['p'][0]},{a['p'][1]},{a['p'][2]}]}}"
        for a in mol["atomlar"]
    ])
    baglar_js = ",".join([f"[{b[0]},{b[1]}]" for b in mol["baglar"]])

    js = f"""
const scene=new THREE.Scene();scene.background=new THREE.Color(0x111122);
const camera=new THREE.PerspectiveCamera(50,innerWidth/innerHeight,0.1,100);camera.position.set(0,2,6);
const renderer=new THREE.WebGLRenderer({{antialias:true}});renderer.setSize(innerWidth,innerHeight);document.body.appendChild(renderer.domElement);
const ctrl=new THREE.OrbitControls(camera,renderer.domElement);ctrl.enableDamping=true;
addEventListener('resize',()=>{{camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight);}});
scene.add(new THREE.AmbientLight(0xffffff,0.5));
const dl=new THREE.DirectionalLight(0xffffff,0.8);dl.position.set(5,5,5);scene.add(dl);

const atomlar=[{atomlar_js}];
const baglar=[{baglar_js}];
const mols=new THREE.Group();

const meshes=[];
atomlar.forEach((a)=>{{
  const m=new THREE.Mesh(new THREE.SphereGeometry(a.r,32,32),new THREE.MeshPhongMaterial({{color:a.c,shininess:80}}));
  m.position.set(a.p[0],a.p[1],a.p[2]);
  mols.add(m);meshes.push(m);
}});

baglar.forEach(b=>{{
  const a1=meshes[b[0]].position,a2=meshes[b[1]].position;
  const dir=new THREE.Vector3().subVectors(a2,a1);
  const len=dir.length();
  const cyl=new THREE.Mesh(new THREE.CylinderGeometry(0.08,0.08,len,16),new THREE.MeshPhongMaterial({{color:0xcccccc}}));
  cyl.position.copy(a1).add(dir.clone().multiplyScalar(0.5));
  cyl.lookAt(a2);cyl.rotateX(Math.PI/2);
  mols.add(cyl);
}});

scene.add(mols);

function animate(){{
  requestAnimationFrame(animate);
  mols.rotation.y+=0.005;
  ctrl.update();renderer.render(scene,camera);
}}
animate();
"""
    return _HTML_SHELL.format(title=mol["isim"], info=info, js=js)


# ════════════════════════════════════════════════════════════════════
# DISPATCH — bot generic prompt'tan template seç
# ════════════════════════════════════════════════════════════════════

def get_template(template_name: str, **kwargs) -> str:
    """
    Bot tool dispatch:
      - "solar_system" / "gunes_sistemi" / "great_attractor" → solar_system_great_attractor()
      - "atom" / "bohr_atom" → atom_model(element=, proton=, neutron=)
      - "hucre" / "cell" → hucre_model(tip="bitki" or "hayvan")
      - "molekul" / "molekül" → molekul_3d(formula="H2O" vb.)
    """
    name = (template_name or "").lower().strip()
    if name in ("solar_system", "gunes_sistemi", "güneş_sistemi", "great_attractor", "ga"):
        return solar_system_great_attractor()
    if name in ("atom", "bohr_atom", "atom_model"):
        return atom_model(
            element=kwargs.get("element", "H"),
            proton=int(kwargs.get("proton", 1)),
            neutron=int(kwargs.get("neutron", 0)),
            electron_shells=kwargs.get("electron_shells"),
        )
    if name in ("hucre", "hücre", "cell", "cell_model"):
        return hucre_model(tip=kwargs.get("tip", "hayvan"))
    if name in ("molekul", "molekül", "molecule", "molekul_3d"):
        return molekul_3d(formula=kwargs.get("formula", "H2O"))
    return solar_system_great_attractor()  # fallback
