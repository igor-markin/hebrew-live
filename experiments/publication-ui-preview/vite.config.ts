import { defineConfig,type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import {existsSync,readFileSync,readdirSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';

const here=fileURLToPath(new URL('.',import.meta.url));
const packageLock=JSON.parse(readFileSync(resolve(here,'package-lock.json'),'utf8'));

function bundledNotices():Plugin{
  return {
    name:'bundled-third-party-notices',
    generateBundle(_options,bundle){
      const packageNames=new Set<string>();
      for(const output of Object.values(bundle)){
        if(output.type!=='chunk')continue;
        for(const moduleId of Object.keys(output.modules)){
          const marker='/node_modules/';
          const offset=moduleId.lastIndexOf(marker);
          if(offset<0)continue;
          const parts=moduleId.slice(offset+marker.length).split('/');
          packageNames.add(parts[0].startsWith('@')?`${parts[0]}/${parts[1]}`:parts[0]);
        }
      }
      const sections=[
        'Hebrew Live CLI bundled web third-party notices',
        '',
        'Generated from the third-party modules included in this Vite output.',
        'Python dependencies and separately downloaded model weights are not bundled in this web output.',
      ];
      const errors=[];
      for(const name of [...packageNames].sort()){
        const packageRoot=resolve(here,'node_modules',name);
        const metadata=JSON.parse(readFileSync(resolve(packageRoot,'package.json'),'utf8'));
        const locked=packageLock.packages?.[`node_modules/${name}`]??{};
        const files=readdirSync(packageRoot).filter(file=>/^(licen[cs]e|copying|notice)(\..*)?$/i.test(file)).sort();
        sections.push('','='.repeat(72),`${metadata.name}@${metadata.version}`,`Declared license: ${metadata.license??'UNDECLARED'}`);
        if(locked.resolved)sections.push(`Locked source: ${locked.resolved}`);
        if(locked.integrity)sections.push(`Locked integrity: ${locked.integrity}`);
        if(!metadata.license)errors.push(`${name}: package metadata has no declared license`);
        if(!locked.resolved||!locked.integrity)errors.push(`${name}: package-lock provenance is incomplete`);
        if(files.length===0){
          sections.push('License evidence: MISSING FROM INSTALLED PACKAGE');
          errors.push(`${name}: installed package has no LICENSE, LICENCE, COPYING, or NOTICE file`);
          continue;
        }
        for(const file of files){
          const path=resolve(packageRoot,file);
          if(!existsSync(path))continue;
          sections.push('',`--- ${file} ---`,readFileSync(path,'utf8').trimEnd());
        }
      }
      if(errors.length)this.error(`Bundled third-party notice check failed:\n${errors.join('\n')}`);
      this.emitFile({type:'asset',fileName:'licenses/THIRD-PARTY-NOTICES.txt',source:`${sections.join('\n')}\n`});
    },
  };
}

export default defineConfig(({mode})=>{
  const runtime=mode==='runtime';
  return {
    base:'./',
    plugins:[react(),tailwindcss(),bundledNotices()],
    server:{host:'127.0.0.1'},
    preview:{host:'127.0.0.1',port:4178,strictPort:true},
    build:{
      outDir:runtime?resolve(here,'../../src/hebrew_live/web'):resolve(here,'dist'),
      emptyOutDir:true,
      rollupOptions:runtime?{input:resolve(here,'live.html')}:undefined,
    },
  };
});
