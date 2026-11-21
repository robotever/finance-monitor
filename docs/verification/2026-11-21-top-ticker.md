# 顶部横向快讯滚动修复

线上旧版复现：正常动态模式CSS动画位移-179.06到-228.764；模拟减少动态效果后animationName=none、前后transform均none。顶部仍采用CSS动画，与已修复的右侧实现不同。这是可复现的停止路径，不代表已经读取用户系统偏好。

修复顶部组件为requestAnimationFrame逐帧更新translateX，复用已有advanceNewsOffset：30px/秒、按时间而非帧率计算、以单份内容宽度循环、后台恢复限幅、无数据时等待。保留手动暂停、鼠标悬停和键盘焦点暂停；组件卸载清理动画。移除旧CSS动画和顶部减少动态效果下隐藏第二份内容的规则。右侧滚动、新闻源及板块数据不改。

验证：已有位移/循环/后台间隔测试2/2通过，vue-tsc与production-rotation构建通过。云端实际位移、暂停恢复、减少动态效果、手机宽度及正式站验证结果见本次部署记录。

云端预览5014851d实测：reduced=true、normal=true（900ms位移超过15px）；paused=true、resumed=true、hovered=true；390px手机mobile=true、overflow=false。原停止路径已通过真实浏览器回归。
