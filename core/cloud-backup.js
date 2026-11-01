var fs=require('fs');
var path=require('path');
var config=require('./config');
function CB(){this.backups=[];this.basePath=path.join(config.paths.backups,'.cloud-backups');if(!fs.existsSync(this.basePath))fs.mkdirSync(this.basePath,{recursive:true});}
CB.prototype.create=function(name,data){var bn=name||'cloud-bak-'+Date.now();var bp=path.join(this.basePath,bn+'.json');var entry={name:bn,createdAt:new Date().toISOString(),size:JSON.stringify(data).length,path:bp};fs.writeFileSync(bp,JSON.stringify({meta:entry,data:data},null,2));this.backups.push(entry);return entry;};
CB.prototype.restore=function(name){var bp=path.join(this.basePath,name+'.json');if(!fs.existsSync(bp))return{success:false,error:'Not found'};var c=JSON.parse(fs.readFileSync(bp,'utf8'));return{success:true,data:c.data,meta:c.meta};};
CB.prototype.list=function(){if(!fs.existsSync(this.basePath))return[];return fs.readdirSync(this.basePath).filter(function(f){return f.endsWith('.json');});};
CB.prototype.delete=function(name){var bp=path.join(this.basePath,name+'.json');if(!fs.existsSync(bp))return false;fs.unlinkSync(bp);return true;};
CB.prototype.getStats=function(){return{total:this.backups.length,basePath:this.basePath};};
module.exports=new CB();
