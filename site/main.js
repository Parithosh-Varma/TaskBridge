// mobile nav, copy buttons, footer year
(function(){
  var b=document.getElementById('burger'),l=document.getElementById('navLinks');
  if(b&&l){b.addEventListener('click',function(){l.classList.toggle('open')});}
  var y=document.getElementById('yr'); if(y){y.textContent=new Date().getFullYear();}
  document.querySelectorAll('[data-copy]').forEach(function(btn){
    btn.addEventListener('click',function(){
      var el=document.getElementById(btn.getAttribute('data-copy'));
      if(!el)return;
      var t=el.innerText;
      function done(){btn.textContent='copied';setTimeout(function(){btn.textContent='copy'},1400);}
      if(navigator.clipboard&&navigator.clipboard.writeText){
        navigator.clipboard.writeText(t).then(done).catch(function(){fallback();});
      }else{fallback();}
      function fallback(){
        var ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);
        ta.select();try{document.execCommand('copy');done();}catch(e){}document.body.removeChild(ta);
      }
    });
  });
})();
