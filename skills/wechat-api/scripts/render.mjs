// Local-only WeChat editorial renderer. Uploads and draft mutations belong to wechat-api.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';

const skill=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const args=process.argv.slice(2);
if(!args[0]||args[0]==='--help'){
  console.log('Usage: node render.mjs <article.md> [--out-dir DIR] [--date YYYY-MM-DD]');
  process.exit(args[0]?0:1);
}
const source=path.resolve(args.shift());
let dest=path.dirname(source),date;
while(args.length){
  const flag=args.shift(),value=args.shift();
  if(!value)throw new Error('Missing value for '+flag);
  if(flag==='--out-dir')dest=path.resolve(value);
  else if(flag==='--date')date=value;
  else throw new Error('Unknown option '+flag);
}
const brand=path.join(skill,'assets/editorial');
const contract=JSON.parse(fs.readFileSync(path.join(brand,'style-contract.json'),'utf8'));
const signature=JSON.parse(fs.readFileSync(path.join(brand,'signature.json'),'utf8'));
const logoSource=path.join(brand,contract.identity.wordmark);
if(crypto.createHash('sha256').update(fs.readFileSync(logoSource)).digest('hex')!==contract.identity.sha256)throw new Error('Fixed WeChat wordmark hash mismatch');
const converter=path.join(skill,'scripts/md2wechat.mjs');
const require=createRequire(converter);
const {load}=require('cheerio');
const matter=require('gray-matter');
const markdown=fs.readFileSync(source,'utf8');
const frontmatter=matter(markdown).data;
const options=frontmatter.wechat||{};
date=date||frontmatter.date||new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Singapore',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
if(date instanceof Date)date=date.toISOString().slice(0,10);
if(!/^\d{4}-\d{2}-\d{2}$/.test(date))throw new Error('Date must be YYYY-MM-DD');
const research=path.join(dest,'research');
fs.mkdirSync(research,{recursive:true});
const meta=JSON.parse(execFileSync(process.execPath,[converter,source,'--no-cite','--theme',path.join(brand,'theme.css'),'--out',path.join(research,'article.converted.html')],{encoding:'utf8'}));
const $=load(fs.readFileSync(meta.htmlPath,'utf8'),{},false);
const article=$('#output');
if(article.length!==1)throw new Error('Expected one converted article');
const c=contract.colors;
const font="-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif";
const rounded="'Arial Rounded MT Bold','Avenir Next',sans-serif";
const pStyle=`margin:0 0 22px;padding:0;font-family:${font};font-size:17px;line-height:30px;font-weight:400;letter-spacing:0;color:${c.text};text-align:left;overflow-wrap:break-word;`;
function styleParagraph(el){
  el.attr('style',pStyle);
  el.find('strong').each((_,n)=>{
    const strong=$(n),keep=Array.from(strong.text()).length<=14?'white-space:nowrap;':'';
    strong.attr('data-article','emphasis').attr('style',`font-weight:600;color:#202120;border-bottom:3px solid ${c.highlightLine};${keep}`);
  });
  el.find('a').attr('style',`color:${c.text};text-decoration:underline;text-underline-offset:3px;`);
}
article.attr('style',`margin:0;padding:0;font-family:${font};color:${c.text};text-align:left;max-width:100%;`).removeAttr('class');
const refTitles=new Set(['参考资料','参考链接']);
const chapterTitles=article.children('h2').toArray().map(x=>$(x).text().trim()).filter(x=>!refTitles.has(x));
const firstParagraph=article.children('p').filter((_,x)=>!$(x).find('img').length).first();
const roundupHeading=options.roundupHeading||contract.content.optionalRoundupHeading;
let referenceMode=false,roundup=false,chapterCount=0,groupCount=0;
const uploadedImages=[];
// Resolve every image, including HTML images and images in lists, quotes or links.
for(const imgNode of article.find('img').toArray()){
  const img=$(imgNode),asset=meta.images.find(x=>x.placeholder===img.attr('src'));
  if(asset){
    if(!fs.existsSync(asset.absolutePath))throw new Error('Missing body image: '+asset.absolutePath);
    const hash=crypto.createHash('sha256').update(fs.readFileSync(asset.absolutePath)).digest('hex').slice(0,12);
    const file=path.join(dest,'assets/article-media',hash+path.extname(asset.absolutePath));
    fs.mkdirSync(path.dirname(file),{recursive:true});fs.copyFileSync(asset.absolutePath,file);
    const relative=path.relative(dest,file).split(path.sep).join('/');
    img.attr('src',relative);
    uploadedImages.push({...asset,placeholder:relative,originalPath:relative,absolutePath:file,role:'body'});
  }else if(!/^https?:/.test(img.attr('src')||''))throw new Error('Unresolved image');
  img.attr('style','display:block;width:100%;max-width:100%;height:auto;border:0;border-radius:12px;margin:0;padding:0;');
}
for(const node of article.children().toArray()){
  const el=$(node),tag=node.tagName,text=el.text().trim();
  if(el.attr('data-surviagi')==='signature')continue;
  el.removeAttr('class').removeAttr('id');
  if(tag==='h2'){
    if(refTitles.has(text)){referenceMode=true;continue;}
    roundup=text.replace(/\s/g,'')===roundupHeading.replace(/\s/g,'');
    chapterCount++;
    const section=$('<section data-article="chapter"></section>').attr('style',`margin:42px 0 26px;padding:22px 0 0;border-top:1px solid ${c.line};`);
    const number=$('<p></p>').text(String(chapterCount).padStart(2,'0')).attr('style',`display:inline-block;margin:0 0 13px;padding:4px 10px;font-family:${rounded};font-size:14px;line-height:21px;font-weight:700;letter-spacing:0;color:${c.localReverse};background:${c.localDark};border-radius:10px;`);
    el.attr('style','margin:0;padding:0;border:0;font-size:24px;line-height:35px;font-weight:700;color:#202120;text-align:left;');
    const keep=options.keepTogether||[];
    const suffix=keep.find(s=>text.endsWith(s));
    if(suffix)el.empty().append($('<span></span>').text(text.slice(0,-suffix.length))).append($('<span style="white-space:nowrap;"></span>').text(suffix));
    el.before(section);section.append(number).append(el);
  }else if(referenceMode){
    continue; // Signature and reference typography are owned by signature.json + converter.
  }else if(tag==='h3'){
    if(roundup&&!text.includes('：')){
      groupCount++;
      const group=$('<section data-article="brief-group"></section>').attr('style',`margin:34px 0 22px;padding:16px 18px;background:${c.localDark};border-radius:12px;`);
      const label=$('<p></p>').text(`周内动向 ${String(groupCount).padStart(2,'0')}`).attr('style',`margin:0 0 5px;padding:0;font-size:12px;line-height:20px;font-weight:600;color:${c.localDarkAccent};`);
      el.attr('style',`margin:0;padding:0;font-size:20px;line-height:30px;font-weight:700;color:${c.localReverse};`);
      el.before(group);group.append(label).append(el);
    }else if(roundup){
      const split=text.indexOf('：'),product=text.slice(0,split),headline=text.slice(split+1);
      const eyebrow=options.featureLabels?.[text]||product;
      el.before($('<p></p>').text(eyebrow).attr('style',`margin:30px 0 8px;padding:0;font-size:13px;line-height:22px;font-weight:600;color:${c.editorialAccent};`));
      el.text(headline).attr('style','margin:0 0 14px;padding:0;font-size:23px;line-height:34px;font-weight:700;color:#202120;');
    }else{
      el.attr('style','margin:28px 0 14px;padding:0;font-size:20px;line-height:30px;font-weight:650;color:#202120;');
    }
  }else if(tag==='h4'){
    el.attr('style','margin:26px 0 12px;padding:0;font-size:18px;line-height:29px;font-weight:650;color:#202120;');
  }else if(tag==='p'){
    const images=el.children('img');
    if(images.length){
      for(const imgNode of images.toArray()){
        // Keep text before each image as a paragraph, preserving source order.
        const before=$('<p></p>');
        while(el.contents().length&&el.contents().first()[0]!==imgNode)before.append(el.contents().first());
        if(before.text().trim()||before.children().length){styleParagraph(before);el.before(before);}
        const img=$(imgNode),caption=img.attr('alt')||'';
        const figure=$('<section></section>').attr('style','margin:22px 0 28px;padding:0;');
        figure.append(img);
        if(caption)figure.append($('<p></p>').text(caption).attr('style',`margin:8px 0 0;font-size:14px;line-height:22px;color:${c.muted};font-weight:400;`));
        el.before(figure);
      }
      if(el.text().trim()||el.children().length)styleParagraph(el);
      else el.remove();
    }else if(roundup&&/^\d{1,2}\s*月\s*\d{1,2}\s*日\s*[—–-]/.test(text)){
      el.attr('style',`margin:0 0 28px;padding:0;font-size:14px;line-height:22px;color:${c.muted};`);
    }else{
      styleParagraph(el);
      const lead=el.children('strong').first();
      if(roundup&&lead.length&&el.contents().first()[0]===lead[0]){
        el.before($('<h4></h4>').text(lead.text().replace(/。$/,'')).attr('style','margin:26px 0 12px;padding:0;font-size:18px;line-height:29px;font-weight:650;color:#202120;'));
        lead.remove();el.html(el.html().trim());
      }
    }
  }else if(tag==='ul'||tag==='ol'){
    el.attr('style',`margin:0 0 22px;padding-left:24px;font-size:17px;line-height:30px;color:${c.text};`);
  }
}
if(firstParagraph.length&&options.lead!==false){
  firstParagraph.attr('style',pStyle.replace('margin:0 0 22px;','margin:0;'));
  const lead=$('<section data-article="lead"></section>').attr('style',`margin:0 0 24px;padding:2px 0 2px 16px;border-left:3px solid ${c.editorialAccent};`);
  firstParagraph.before(lead);lead.append(firstParagraph);
}
if(chapterTitles.length>=2&&options.contents!==false){
  const toc=$('<section data-article="contents"></section>').attr('style',`margin:0 0 26px;padding:18px 20px 14px;border:1px solid ${c.localDark};border-radius:12px;`);
  toc.append($('<p></p>').text('本期目录').attr('style',`margin:0 0 12px;padding:0;font-size:14px;line-height:22px;font-weight:600;color:${c.editorialAccent};`));
  chapterTitles.forEach((heading,i)=>{
    const n=['一','二','三','四','五','六','七','八','九','十'][i]||String(i+1);
    toc.append($('<p></p>').text(n+'、'+heading).attr('style','margin:0 0 7px;padding:0;font-size:15px;line-height:26px;font-weight:400;color:#555555;'));
  });
  article.prepend(toc);
}
const signatureNode=article.find('[data-surviagi="signature"]');
if(signatureNode.length!==1||signatureNode.text().trim()!==signature.textTemplate.replace('{brand}',signature.brand))throw new Error('Add the canonical signature once before references in Markdown; see assets/editorial/signature.json');
const logoDest=path.join(dest,'assets/brand/surviagi-horizontal-en-light.png');
fs.mkdirSync(path.dirname(logoDest),{recursive:true});fs.copyFileSync(logoSource,logoDest);
const logoRelative=path.relative(dest,logoDest).split(path.sep).join('/');
signatureNode.before($('<section data-surviagi="brand-signature" style="margin:32px 0 0;padding:0;"></section>').append($('<img>').attr({src:logoRelative,alt:'SurviAGI',style:'display:block;width:300px;max-width:100%;height:auto;border:0;margin:0 auto;padding:0;'})));
uploadedImages.push({placeholder:logoRelative,originalPath:logoRelative,absolutePath:logoDest,alt:'SurviAGI',title:'',role:'brand'});
const fragment=$.html();
fs.writeFileSync(path.join(dest,'article.wechat.html'),fragment);
const title=$('<h1></h1>').text(meta.title).attr('style','margin:0 0 14px;font-size:22px;line-height:31px;font-weight:600;letter-spacing:0;color:#202120;').toString();
const displayDate=date.replace(/^(\d{4})-(\d{2})-(\d{2})$/,(_,y,m,d)=>`${y}年${Number(m)}月${Number(d)}日`);
const byline=$('<p></p>').attr('style','margin:0 0 30px;font-size:14px;line-height:24px;color:#999999;').append($('<span style="color:#576B95;"></span>').text(signature.brand.split('（')[0])).append($('<span style="display:inline-block;margin-left:12px;"></span>').text(displayDate)).toString();
const preview=`<header data-preview-only="wechat-header">${title}${byline}</header>`+fragment;
fs.writeFileSync(path.join(dest,'article-preview.html'),`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${$('<span>').text(meta.title).html()}</title><style>*{box-sizing:border-box}html{background:#FFFFFF}body{margin:0;background:#FFFFFF;color:${c.text};font-family:${font}}main{max-width:677px;margin:0 auto;padding:20px 20px 64px}a{overflow-wrap:anywhere}img{max-width:100%}@media(min-width:760px){main{padding:32px 0 80px}}</style></head><body><main>${preview}</main></body></html>`);
meta.htmlPath=path.join(dest,'article.wechat.html');meta.previewPath=path.join(dest,'article-preview.html');meta.htmlLength=fragment.length;meta.images=uploadedImages;meta.sourceMarkdown=source;meta.visualContractVersion=contract.version;meta.writingStatus=contract.writingStatus;
fs.writeFileSync(path.join(research,'article-conversion.json'),JSON.stringify(meta,null,2)+'\n');
const checks={contractVersion:contract.version,logoSha256:contract.identity.sha256,chapterCount,briefGroupCount:groupCount,bodyImageCount:uploadedImages.filter(x=>x.role==='body').length,brandImageCount:1,referenceCount:article.children('p').filter((_,p)=>/^\[\d+\]/.test($(p).text())).length,signatureCount:signatureNode.length,brandSignatureCount:article.find('[data-surviagi="brand-signature"]').length,bodyBackground:'transparent',previewBackground:'#FFFFFF',writingStatus:contract.writingStatus,externalWrite:false};
if(fragment.includes('WECHATIMG_'))throw new Error('Image placeholder remaining');
fs.writeFileSync(path.join(research,'article-layout-check.json'),JSON.stringify(checks,null,2)+'\n');
console.log(JSON.stringify({source,dest,...checks},null,2));
