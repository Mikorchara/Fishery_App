import test from 'node:test';
import assert from 'node:assert/strict';
import {createVideoPreview} from '../static/components.js';
import {Element} from './dom-fixture.mjs';

function installDOM(){
  const oldDocument=globalThis.document,oldNode=globalThis.Node;
  globalThis.Node=Element;
  globalThis.document={createElement:t=>new Element(t),createTextNode:text=>{const n=new Element('text');n.textContent=text;return n;}};
  return ()=>{globalThis.document=oldDocument;globalThis.Node=oldNode;};
}

const walk=n=>[n,...n.children.flatMap(walk)];
test('local player is stable across polling and independent of camera selection',()=>{
  const restore=installDOM();
  try{
    const host=new Element(),preview=createVideoPreview(host),meta={kind:'local_file',url:'/media/local-demo.mp4'};
    preview.update(meta,false);assert.equal(host.children.length,0);
    preview.update(meta,true);
    const video=walk(host).find(n=>n.tagName==='video');assert.ok(video);
    video.currentTime=18;let pauses=0;video.pause=()=>pauses++;
    preview.update(meta,true);preview.update({...meta},true);
    assert.equal(walk(host).find(n=>n.tagName==='video'),video);assert.equal(video.currentTime,18);
    assert.match(host.textContent,/未执行实时视频分析/);
    preview.update(meta,false);assert.equal(host.hidden,true);assert.equal(pauses,1);
    preview.update(meta,true);assert.equal(walk(host).find(n=>n.tagName==='video'),video);
    preview.suspend();assert.equal(pauses,2);
    preview.update(null);assert.equal(host.hidden,true);assert.equal(video.getAttribute('src'),null);
  }finally{restore();}
});

test('media metadata is restricted to the two same-origin video routes',()=>{
  const restore=installDOM();
  try{
    for(const meta of [
      {kind:'local_file',url:'https://evil.invalid/v.mp4'},
      {kind:'local_file',url:'file:///private.mp4'},
      {kind:'local_file',url:'/media/board-video.mjpg'},
      {kind:'board_stream',source_kind:'DEVICE_RTSP',url:'https://evil.invalid/v.mjpg'},
      {kind:'board_stream',source_kind:'DEVICE_RTSP',url:'/media/local-demo.mp4'},
      {kind:'board_stream',source_kind:'SIMULATOR',url:'/media/board-video.mjpg'},
    ]){
      const host=new Element(),preview=createVideoPreview(host);
      assert.equal(preview.available(meta),false);
      preview.update(meta,true);
      assert.equal(host.hidden,true);assert.equal(host.children.length,0);
    }
  }finally{restore();}
});
