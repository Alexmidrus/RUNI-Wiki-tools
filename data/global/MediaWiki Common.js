/* Any JavaScript here will be loaded for all users on every page load. */

/** Collapsible tables *********************************************************
 *
 *  Description: Allows tables to be collapsed, showing only the header. See
 *               http://www.mediawiki.org/wiki/Manual:Collapsible_tables.
 *  Maintainers: [[**MAINTAINERS**]]
 */
var autoCollapse = 2;
var collapseCaption = 'скрыть';
var expandCaption = 'показать';

function collapseTable( tableIndex ) {
	var Button = document.getElementById( 'collapseButton' + tableIndex );
	var Table = document.getElementById( 'collapsibleTable' + tableIndex );
 
	if ( !Table || !Button ) {
		return false;
	}
 
	var Rows = Table.rows;
 
	if ( Button.firstChild.data == collapseCaption ) {
		for ( var i = 1; i < Rows.length; i++ ) {
			Rows[i].style.display = 'none';
		}
		Button.firstChild.data = expandCaption;
	} else {
		for ( var i = 1; i < Rows.length; i++ ) {
			Rows[i].style.display = Rows[0].style.display;
		}
		Button.firstChild.data = collapseCaption;
	}
}


function createCollapseButtons() {
	var tableIndex = 0;
	var NavigationBoxes = new Object();
	var Tables = document.getElementsByTagName( 'table' );
 
	for ( var i = 0; i < Tables.length; i++ ) {
		if ( hasClass( Tables[i], 'collapsible' ) ) {
			/* only add button and increment count if there is a header row to work with */
			var HeaderRow = Tables[i].getElementsByTagName( 'tr' )[0];
			if( !HeaderRow ) continue;
			var Header = HeaderRow.getElementsByTagName( 'th' )[0];
			if( !Header ) continue;
 
			NavigationBoxes[tableIndex] = Tables[i];
			Tables[i].setAttribute( 'id', 'collapsibleTable' + tableIndex );
 
			var Button     = document.createElement( 'span' );
			var ButtonLink = document.createElement( 'a' );
			var ButtonText = document.createTextNode( collapseCaption );
 
			Button.className = 'collapseButton'; // Styles are declared in MediaWiki:Common.css
 
			ButtonLink.style.color = Header.style.color;
			ButtonLink.setAttribute( 'id', 'collapseButton' + tableIndex );
			ButtonLink.setAttribute( 'href', "javascript:collapseTable(" + tableIndex + ");" );
			ButtonLink.appendChild( ButtonText );
 
			Button.appendChild( document.createTextNode( '[' ) );
			Button.appendChild( ButtonLink );
			Button.appendChild( document.createTextNode( ']' ) );
 
			Header.insertBefore( Button, Header.childNodes[0] );
			tableIndex++;
		}
	}
 
	for ( var i = 0;  i < tableIndex; i++ ) {
		if ( hasClass( NavigationBoxes[i], 'collapsed' ) || ( tableIndex >= autoCollapse && hasClass( NavigationBoxes[i], 'autocollapse' ) ) ) {
			collapseTable( i );
		}
	}
}


//addOnloadHook( createCollapseButtons );
$( createCollapseButtons ); //RayEdit1.33

/** Test if an element has a certain class **************************************
 *
 * Description: Uses regular expressions and caching for better performance.
 * Maintainers: [[User:Mike Dillon]], [[User:R. Koot]], [[User:SG]]
 */
 
var hasClass = (function() {
	var reCache = {};
	return function( element, className ) {
		return (reCache[className] ? reCache[className] : (reCache[className] = new RegExp("(?:\\s|^)" + className + "(?:\\s|$)"))).test(element.className);
	};
})();

/** Eve University Tooltip *********************************************************
 *
 *  Description: Allows easy use of auto-generated tooltip
 *               http://wiki.eveuniversity.org/Template:Tooltip
 *  Maintainers: Sarah Schneider
 **********************************************************/
 var _tooltipClassName = 'uniwiki-tooltip';
 var _tooltipFrameClassName = 'uniwiki-tooltip-frame';
 var _activeTooltipIdx = -1;
 var _posCorrectionX = 20; var _posCorrectionY = 10;
 var _ratioWidth = 5; var _ratioHeight = 1;
function checkElementByClassComp() {
	if (document.getElementsByClassName == undefined) {
		document.getElementsByClassName = function(className)
		{
			var hasClassName = new RegExp("(?:^|\\s)" + className + "(?:$|\\s)");
			var allElements = document.getElementsByTagName("*");
			var results = [];

			var element;
			for (var i = 0; (element = allElements[i]) != null; i++) {
				var elementClass = element.className;
				if (elementClass && elementClass.indexOf(className) != -1 && hasClassName.test(elementClass))
					results.push(element);
			}
			return results;
		}
	}
}
function createTooltipTrigger() {
	var tooltips = document.getElementsByClassName(_tooltipClassName);
	for(var i=0;i<tooltips.length;i++) {
		tooltips[i].setAttribute( 'id', 'tooltipidx-' + i );
		tooltips[i].setAttribute( 'onmouseover', 'showTooltip(' + i + ')' );
		tooltips[i].setAttribute( 'onmouseout', 'hideTooltip()');
		
		var matchFrameClassName = new RegExp("(?:^|\\s)" + _tooltipFrameClassName + "(?:$|\\s)");
		var innerTooltipEls = tooltips[i].getElementsByTagName('*');
		for(var j=0;(innerEl = innerTooltipEls[j]) != null;j++) {
			if(innerEl.className && innerEl.className.indexOf(_tooltipFrameClassName) != -1 && matchFrameClassName.test(innerEl.className)) {
				innerTooltipEls[j].setAttribute( 'id', 'tooltipframeidx-' + i ); break;
			}
		}
	}
}
function tooltipMouseHandler(e) {
	if (!e){ e = window.event; }
	mouseX = null; mouseY = null;
	if(e.pageX && e.pageY) { mouseX = e.pageX; mouseY = e.pageY; }
	else if(e.clientX && e.clientY) {
		mouseX = e.clientX + (document.documentElement.scrollLeft ? document.documentElement.scrollLeft : document.body.scrollLeft);
		mouseY = e.clientY + (document.documentElement.scrollLeft ? document.documentElement.scrollLeft : document.body.scrollLeft);
	}
	moveTooltip(mouseX, mouseY);
}
function moveTooltip(x, y) {
	if(_activeTooltipIdx != -1) {
		var parentObj = document.getElementById('tooltipidx-' + _activeTooltipIdx);
		var parentPos = findPos(parentObj);
		var frameObj = document.getElementById('tooltipframeidx-' + _activeTooltipIdx);
		var windowSize = getWindowSize();
		
		if(frameObj.offsetWidth < frameObj.offsetHeight)
		{
			frameObj.style.width = (_ratioWidth / (_ratioWidth + _ratioHeight)) * (frameObj.offsetWidth + frameObj.offsetHeight) + 'px';			
		}
		
		var maxTooltipWidth = windowSize.width > 800 ? (0.6 * windowSize.width) : (0.8 * windowSize.width);
		
		if((frameObj.offsetWidth + 20) > maxTooltipWidth)
		{
			frameObj.style.width = maxTooltipWidth + 'px';
			frameObj.style.left = ((x - parentPos.x) + _posCorrectionX) + 'px';	
		}
		
		if((frameObj.offsetWidth + parentPos.x + 70) < windowSize.width) {
			frameObj.style.left = ((x - parentPos.x) + _posCorrectionX) + 'px';			
		}else {
			frameObj.style.left = ((x - parentPos.x) - frameObj.offsetWidth - _posCorrectionX) + 'px';
		}
		frameObj.style.top = ((y - parentPos.y) + _posCorrectionY) + 'px'; 
	}
	return false;
}
function findPos(obj) {
	var curleft = curtop = 0;
	var position = new Object();
	if (obj.offsetParent) {
		curleft = obj.offsetLeft
		curtop = obj.offsetTop
		while (obj = obj.offsetParent) {
			curleft += obj.offsetLeft
			curtop += obj.offsetTop
		}
	}
	position.x = curleft;
	position.y = curtop;
	return position;
}
function getWindowSize() {
  var size = new Object();
  if( typeof( window.innerWidth ) == 'number' ) {
    //Non-IE
    size.width = window.innerWidth;
    size.height = window.innerHeight;
  } else if( document.documentElement && ( document.documentElement.clientWidth || document.documentElement.clientHeight ) ) {
    //IE 6+ in 'standards compliant mode'
    size.width = document.documentElement.clientWidth;
    size.height = document.documentElement.clientHeight;
  } else if( document.body && ( document.body.clientWidth || document.body.clientHeight ) ) {
    //IE 4 compatible
    size.width = document.body.clientWidth;
    size.height = document.body.clientHeight;
  }
  return size;
}
function showTooltip(id) {
	_activeTooltipIdx = id;
	document.onmousemove = tooltipMouseHandler;
	document.getElementById( 'tooltipframeidx-' + id ).style.display = 'block';
}
function hideTooltip() {
	_activeTooltipIdx = -1;
	document.onmousemove = null;
	var allTooltip = document.getElementsByClassName(_tooltipFrameClassName);
	for(var i=0;(tooltipEl = allTooltip[i]) != null;i++) {
		tooltipEl.style.display = 'none';
	}	
} 
//addOnloadHook(checkElementByClassComp);
$( checkElementByClassComp ); //RayEdit1.33
//addOnloadHook(createTooltipTrigger);
$( createTooltipTrigger ); //RayEdit1.33

/** Eve University New Fitting Template *******************
*
* Description: Allows showing and hiding of EFT, recommended skills, and notes section
*	 Allows viewing of fit and module info in game
* Adds titles to modules for viewing when hovering over picture
* 
* Maintainers: Miranda McLaughlin
**********************************************************/

try{
(function($) {
$(function() {

$(function() {
//$('.shipFitting .button.eve').on('click', showFitInGame);
$('.shipFitting .button.eft').on('click', toggleEFT);
$('.shipFitting .button.skills').on('click', toggleSkills);
$('.shipFitting .button.notes').on('click', toggleNotes);

//$('.shipFitting .module').not('.open, .inactive').on('click', showItemInfoInGame);
//$('.shipFitting .subMod').not('.open, .inactive').on('click', showItemInfoInGame);
//$('.shipFitting .shipInfo').on('click', showItemInfoInGame);

$('.shipFitting .module:not(.open, .inactive)').each(addTitle);
$('.shipFitting .subMod:not(.open, .inactive)').each(addTitle);
});

//function showFitInGame() {
//var dna = $(this).attr("data-shipdna");
//CCPEVE.showFitting(dna);
//}

function toggleEFT() {
$(this).toggleClass('active');
$(this).parents('.shipFitting').find('.moreInfo.eftData').toggleClass('show');
$(this).parents('.shipFitting').toggleClass('showEFT');
}

function toggleSkills() {
$(this).toggleClass('active');
$(this).parents('.shipFitting').find('.moreInfo.skills').toggleClass('show');
$(this).parents('.shipFitting').toggleClass('showSkills');
}

function toggleNotes() {
$(this).toggleClass('active');
$(this).parents('.shipFitting').find('.moreInfo.notes').toggleClass('show');
$(this).parents('.shipFitting').toggleClass('showNotes');
}

//function showItemInfoInGame() {
//var typeID = $(this).attr('data-typeid');
//CCPEVE.showInfo(typeID);
//}

function addTitle(index, element) {
var name = $(element).attr('data-name');
$(element).find('img').attr('title', name);
}
});
})(jQuery);
}catch(e){console.log("Joel screwed up! Contact Miranda McLaughlin.", e);}

/** EVE-University - Fitting Template *******************
*
* Description: Opens Fleet-Up in a new window
*
* Maintainers: Pehuen
**********************************************************/

try{
(function($) {
$(function() {

$(function() {
$('.shipFitting .button.fleetup').on('click', showFleetUp);
});

function showFleetUp() {
    var fleetup = $(this).attr("data-fleetup");
    var fleetup_url = fleetup;
    window.open(fleetup_url, fleetup);
    return false;
}

});
})(jQuery);
}catch(e){console.log("Pehuen screwed up! Post on the forums.", e);}


mw.loader.using(['mediawiki.util'], function () {
  $(function () {
    console.log("✅ Citizen Search Trigger Loaded");

    const fakeSearchBox = document.getElementById('skin-citizen-search-trigger');
    const realSearchToggle = document.getElementById('citizen-search-details');

    if (!fakeSearchBox) {
      console.log("⚠️ Fake search box not found.");
      return;
    }

    fakeSearchBox.addEventListener('click', function () {
      console.log("🔍 Search trigger clicked");

      if (realSearchToggle) {
        realSearchToggle.open = true;
        setTimeout(() => {
          const input = document.getElementById('searchInput');
          if (input) input.focus();
        }, 100);
      } else {
        console.log("❌ Real search toggle not found, falling back to / key");
        const event = new KeyboardEvent('keydown', {
          key: '/',
          keyCode: 191,
          code: 'Slash',
          which: 191,
          bubbles: true,
          cancelable: true
        });
        document.dispatchEvent(event);
      }
    });
  });
});

mw.loader.using(['jquery', 'mediawiki.api'], function () {
    $(function () {
        $('.main-banner[data-files]').each(function () {
            var $box = $(this);
            
            var list = String($box.attr('data-files'))
                .split(/\s*\|\s*|\s*,\s*/)
                .filter(Boolean);

            if (!list.length) return;

            var pick = list[Math.floor(Math.random() * list.length)];

            // Use MediaWiki API to resolve actual file path
            new mw.Api().get({
                action: 'query',
                titles: 'File:' + pick,
                prop: 'imageinfo',
                iiprop: 'url',
                format: 'json'
            }).done(function (data) {
                var pages = data.query.pages;
                for (var pageId in pages) {
                    if (pages.hasOwnProperty(pageId) && pages[pageId].imageinfo) {
                        var url = pages[pageId].imageinfo[0].url;
                        var $img = $('<img>', {
                            src: url,
                            width: 2450,
                            height: 450,
                            alt: ''
                        });
                        $box.empty().append($img);
                    }
                }
            });
        });
    });
});

/** Template:ShipArticle — скрипт навыков *******************************
 *
 * Добавить в КОНЕЦ существующего MediaWiki:Common.js
 * Никаких внешних загрузок — весь код здесь.
 ************************************************************************/
( function () {
    'use strict';

    var ROMAN = { 'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5 };

    function parseLevel( text ) {
        var t = text.replace( /\u00a0/g, ' ' ).trim();
        var m = t.match( /\b(V|IV|III|II|I)\s*$/ );
        return m ? ( ROMAN[ m[1] ] || 0 ) : 0;
    }

    function stripLevel( text ) {
        return text.replace( /[\u00a0\s]+(V|IV|III|II|I)\s*$/, '' ).trim();
    }

    function buildDots( level ) {
        var wrap = document.createElement( 'span' );
        wrap.className = 'skill-dots';
        for ( var i = 1; i <= 5; i++ ) {
            var d = document.createElement( 'span' );
            d.className = 'dot' + ( i <= level ? ' filled' : '' );
            wrap.appendChild( d );
        }
        return wrap;
    }

    function parseLi( li ) {
        var a = li.querySelector( 'a' );
        var level = 0;
        var nameHTML = '';

        if ( a ) {
            var fullText = ( a.textContent || a.innerText || '' );
            level = parseLevel( fullText );
            var aClone = a.cloneNode( false );
            aClone.textContent = stripLevel( fullText );
            nameHTML = aClone.outerHTML;
        }

        var time = '';
        li.childNodes.forEach( function ( node ) {
            if ( node.nodeName === 'SMALL' ) {
                time = ( node.textContent || '' ).trim();
            }
        } );

        return { level: level, nameHTML: nameHTML, time: time };
    }

    function buildRow( data, isChild ) {
        var tr = document.createElement( 'tr' );

        var tdDots = document.createElement( 'td' );
        tdDots.className = 'col-dots';
        tdDots.appendChild( buildDots( data.level ) );

        var tdName = document.createElement( 'td' );
        tdName.className = 'col-name' + ( isChild ? ' child' : '' );
        tdName.innerHTML = data.nameHTML;

        var tdTime = document.createElement( 'td' );
        tdTime.className = 'col-time';
        tdTime.textContent = data.time;

        tr.appendChild( tdDots );
        tr.appendChild( tdName );
        tr.appendChild( tdTime );
        return tr;
    }

    function processUl( ul, tbody, isChild ) {
        ul.querySelectorAll( ':scope > li' ).forEach( function ( li ) {
            tbody.appendChild( buildRow( parseLi( li ), isChild ) );
            li.querySelectorAll( ':scope > ul' ).forEach( function ( nested ) {
                processUl( nested, tbody, true );
            } );
        } );
    }

    function initSkills( container ) {
        if ( !container ) return;
        if ( container.querySelector( '.skills-table' ) ) return;

        var firstUl = container.querySelector( 'ul' );
        if ( !firstUl ) return;

        var table = document.createElement( 'table' );
        table.className = 'skills-table';
        var tbody = document.createElement( 'tbody' );

        var rootLists = container.querySelectorAll( ':scope > ul' );
        if ( rootLists.length ) {
            rootLists.forEach( function ( ul ) { processUl( ul, tbody, false ); } );
        } else {
            processUl( firstUl, tbody, false );
        }

        table.appendChild( tbody );

        var titleDiv = container.querySelector( '.title' );
        if ( titleDiv ) {
            titleDiv.insertAdjacentElement( 'afterend', table );
        } else {
            container.insertBefore( table, firstUl );
        }
    }

    function run( $content ) {
        var root = ( $content && $content[0] ) ? $content[0] : document;
        if ( !root.querySelector( '#ship-article' ) ) return;
        var container = root.querySelector( '#ship-article .midinfo .left' );
        initSkills( container );
    }

    mw.hook( 'wikipage.content' ).add( run );

}() );
