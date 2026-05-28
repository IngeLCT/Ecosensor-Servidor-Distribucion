from pathlib import Path

from nicegui import ui, app


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = PROJECT_ROOT / 'static'

# Sirve la carpeta /static del proyecto.
# Si después mueves esta línea a main.py, puedes borrar este bloque de aquí.
if STATIC_DIR.exists():
    try:
        app.add_static_files('/static', STATIC_DIR)
    except Exception:
        # Evita error si /static ya fue registrado en main.py u otro módulo.
        pass


POLLUTANTS = {
    'pm25': {
        'short': 'PM₂.₅',
        'title': 'Partículas Finas (PM₂.₅)',
        'thumb': '/static/pm.png',
        'image': '/static/pm_particulas.png',
        'caption': 'source: US EPA',
        'html': '''
            <h4>Puntos clave:</h4>
            <ul>
            <li>Las partículas pequeñas en el aire, especialmente las inferiores a  <b>&lt; 2.5 μm (0,0025 mm),</b> 
               son peligrosas y pueden causar graves consecuencias para la salud a largo plazo.</li>
            <li>Existen índices y colores contradictorios en diferentes países. Asegúrese de conocer el valor de PM2.5 en μg/m³.</li>
            <li>No existen niveles seguros de PM. Deben ser lo más bajos posible. La OMS recomienda un promedio anual inferior a 5 μg/m³.</li>
            <li>Utilice purificadores de aire con filtro <b> HEPA</b>  en interiores o mascarillas <b>N95</b>  en exteriores para reducir su exposición.</li>
            </ul>
            <h5>Organización Mundial de la Salud: Mantenga el nivel anual de PM2.5 por debajo de <b>5 μg/m³</b>. Cuanto más cercano a cero, mejor.</h5>
            <h5>Índice de Calidad del Aire (ICA). Esperanza de vida que se pierde debido a la contaminación del aire por PM. https://aqli.epic.uchicago.edu/the-index/</h5>
        ''',
    },
    'co2': {
        'short': 'CO₂',
        'title': 'Dióxido de carbono (CO₂)',
        'thumb': '/static/co2.png',
        'image': '/static/co2ES.png',
        'caption': 'La ventilación y la ocupación influyen directamente',
        'html': '''
            <h4>Puntos clave:</h4>
            <ul>
            <li>El dióxido de carbono (CO₂) es un gas presente en la atmósfera y su concentración exterior ronda las 430 ppm.</li>
            <li>Al respirar, exhalamos CO₂, por lo que su concentración puede aumentar rápidamente en lugares cerrados.</li>
            <li>Los altos niveles de CO₂ pueden causar dolores de cabeza y afectar el rendimiento cerebral.</li>
            <li>Para reducir la concentración de CO₂, puede abrir las ventanas o aumentar el flujo de aire fresco de su sistema de climatización.</li>
            <li>Tenga en cuenta que los sistemas de aire acondicionado convencionales de pared no reducen la concentración de CO₂, ya que solo recirculan el aire interior.</li>
            <li>La mayoría de los sensores de CO2 realizan una calibración automática de referencia (ABC). Para que funcionen correctamente, la habitación debe ventilarse con frecuencia, por ejemplo, una vez por semana. De lo contrario, estos sensores podrían mostrar lecturas demasiado bajas.</li>
            <li>Asegúrese de que su sensor de CO2 utilice tecnología NDIR, ya que este tipo de sensores mide el CO2 de forma directa y precisa.</li>
            </ul>
        ''',
    },
    'voc': {
        'short': 'VOC',
        'title': 'Compuestos Orgánicos Volátiles (VOC)',
        'thumb': '/static/voc.png',
        'image': '/static/voc_homeES.png',
        'caption': 'Fuentes comunes y recomendaciones',
        'html': '''
            <h4>Puntos clave:</h4>
            <ul>
            <li>Hay más de 10000 VOC en el aire. Algunos son extremadamente dañinos, otros inocuos. Ambos influyen en los valores de VOC. 
            Por lo tanto, es fundamental conocer el VOC específico para tomar una decisión informada.</li>
            <li>Los sensores de VOC antiguos de algunos monitores de calidad del aire se probaban en laboratorios especializados con un solo 
              tipo de alcohol (etanol). Esto no refleja la calidad del aire en el mundo real, donde existen muchos VOC diferentes. Por lo tanto, 
              los valores que muestran estos sensores podrían no indicar con exactitud la cantidad de VOC dañinos presentes en el aire.</li>
            <li>Los sensores más modernos se centran ahora en la variación de los VOC en, por ejemplo, las últimas 24 horas, en lugar de las concentraciones absolutas.</li>
            <li>Si observa picos a lo largo del día y puede identificar la fuente, puede intentar reducir la exposición a estas sustancias químicas.</li>
            </ul>
        ''',
    },
    'nox': {
        'short': 'NOₓ',
        'title': 'Óxidos de Nitrógeno (NOₓ)',
        'thumb': '/static/nox.png',
        'image': '/static/traffic_pollution.png',
        'caption': 'Tráfico y combustión: principales fuentes',
        'html': '''
            <h4>Puntos clave:</h4>
            <ul>
            <li>El NOx es la suma del óxido nítrico (NO) y el dióxido de nitrógeno (NO₂). Estos dos contaminantes tienen propiedades similares y 
              participan en muchos de los mismos procesos químicos en la atmósfera.</li>
            <li>La exposición al NOx se asocia con enfermedades cardiovasculares, asma, diabetes mellitus, hipertensión, accidente cerebrovascular 
              y enfermedad pulmonar obstructiva crónica (EPOC).</li>
            <li>El NOx se genera por la combustión en motores (automóviles, camiones, barcos, aeronaves e industrias). Por lo tanto, representa un 
              problema particular en las zonas urbanas. Sin embargo, las actividades agrícolas y algunos fenómenos naturales también pueden generarlo.</li>
            <li>El NOx también contribuye a la formación de esmog, lluvia ácida y ozono troposférico.</li>
            </ul>
        ''',
    },
}


def pollutants_info_card() -> None:
    """Tarjeta + modal de información sobre contaminantes."""

    ui.add_head_html('''
    <style>
        .card-pollutants-ng {
            background: #cce5dc;
            border-radius: 14px;
            border: 2px solid rgba(31,113,184,.35);
            box-shadow: 0 3px 10px rgba(0,0,0,.10), 0 18px 36px rgba(0,0,0,.15);
            padding: 18px 22px 26px;
            margin-bottom: 24px;
            width: 100%;
        }
    
        .card-pollutants-title-ng {
            color: #000;
            font-size: 26px;
            font-weight: bold;
            text-align: center;
            width: 100%;
            display: block;
            margin: 0;
        }
    
        .card-pollutants-sub-ng {
            color: #000;
            font-size: 20px;
            text-align: center;
            width: 100%;
            display: block;
            margin: 12px 0 18px;
        }
    
        .thumbs-ng {
            display: grid;
            gap: 26px;
            grid-template-columns: repeat(4, minmax(140px, 1fr));
            justify-items: center;
            align-items: start;
            width: 100%;
        }
    
        @media (max-width: 960px) {
            .thumbs-ng {
                grid-template-columns: repeat(2, minmax(160px, 1fr));
            }
        }
    
        @media (max-width: 520px) {
            .thumbs-ng {
                grid-template-columns: 1fr;
            }
        }
    
        .thumb-ng {
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: flex-start !important;
            gap: 8px !important;
            border: 0 !important;
            background: transparent !important;
            cursor: pointer;
            padding: 0 !important;
            margin: 0 !important;
            color: inherit !important;
            box-shadow: none !important;
            min-height: auto !important;
            width: 190px !important;
        }
    
        .thumb-ng .q-btn__content {
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: flex-start !important;
            gap: 8px !important;
            width: 100%;
        }
    
        .thumb-img-ng {
            width: 180px;
            height: 100px;
            max-width: 100%;
            object-fit: cover;
            display: block;
            border-radius: 10px;
            background: #cce5dc;
            box-shadow: 0 3px 10px rgba(0,0,0,.12);
            transition: transform .13s ease, box-shadow .13s ease;
        }
    
        .thumb-ng:hover .thumb-img-ng {
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(0,0,0,.18);
        }
    
        .thumb-label-ng {
            margin-top: 4px;
            color: #0f2741;
            font-weight: 700;
            font-size: 18px;
            text-align: center;
        }
    
        .pollutant-dialog-card-ng {
            width: min(96vw, 1400px) !important;
            height: calc(100vh - 8vh) !important;
            height: calc(100dvh - 8vh) !important;
            max-height: calc(100vh - 8vh) !important;
            max-height: calc(100dvh - 8vh) !important;
            max-width: 1400px !important;
            background: #cce5dc !important;
            border-radius: 14px !important;
            overflow: hidden;
            padding: 0 !important;
            display: flex !important;
            flex-direction: column !important;
        }
    
        .pollutant-dialog-header-ng {
            background: #80ffd4;
            color: #000;
            padding: .9rem 1.1rem;
            width: 100%;
            flex: 0 0 auto;
        }
    
        .pollutant-dialog-title-ng {
            font-size: clamp(20px, 1.75vw, 32px);
            font-weight: bold;
            line-height: 1.2;
        }
    
        .pollutant-dialog-body-ng {
            flex: 1 1 auto;
            min-height: 0;
            padding: 1.1rem 1.2rem 1.4rem;
            overflow-y: auto;
            overflow-x: hidden;
            width: 100%;
            -webkit-overflow-scrolling: touch;
            overscroll-behavior: contain;
        }
    
        .pollutant-modal-grid-ng {
            display: grid;
            grid-template-columns: 1.05fr 1fr;
            gap: 1.2rem;
            min-height: 0;
            height: 100%;
        }
    
        .pollutant-text-ng {
            text-align: left;
            font-size: clamp(16px, 1.2vw, 22px);
            line-height: 1.5;
        }
    
        .pollutant-text-ng h4 {
            font-size: clamp(20px, 1.75vw, 30px);
            margin: .2rem 0 .6rem;
            font-weight: bold;
        }
    
        .pollutant-text-ng h5 {
            font-size: clamp(16px, 1.25vw, 22px);
            margin: .6rem 0;
            line-height: 1.5;
        }
    
        .pollutant-text-ng ul {
            margin: .4rem 0 0 1.1rem;
        }
    
        .pollutant-text-ng li {
            margin: .45rem 0;
        }
    
        .pollutant-image-card-ng {
            display: grid;
            grid-template-rows: minmax(0, 1fr) auto;
            height: 100%;
            min-height: 0;
            overflow: hidden;
            border-radius: 10px;
            background: #cce5dc;
        }
    
        .pollutant-image-card-ng img {
            width: 100%;
            height: 100%;
            max-height: 100%;
            object-fit: contain;
        }
    
        .pollutant-caption-ng {
            padding: .35rem .6rem;
            font-size: 18px;
            color: #404040;
            background: #cce5dc;
            text-align: center;
        }
    
        /* Ajuste especial para celular */
        @media (max-width: 860px) {
            .pollutant-dialog-card-ng {
                width: 96vw !important;
                height: calc(100vh - 24px) !important;
                height: calc(100dvh - 24px) !important;
                max-height: calc(100vh - 24px) !important;
                max-height: calc(100dvh - 24px) !important;
                border-radius: 12px !important;
            }
    
            .pollutant-dialog-header-ng {
                padding: .75rem .9rem;
            }
    
            .pollutant-dialog-title-ng {
                font-size: 20px;
                line-height: 1.2;
            }
    
            .pollutant-dialog-body-ng {
                flex: 1 1 auto;
                min-height: 0;
                padding: 1rem;
                overflow-y: auto;
                overflow-x: hidden;
                -webkit-overflow-scrolling: touch;
            }
    
            .pollutant-modal-grid-ng {
                grid-template-columns: 1fr;
                height: auto;
                min-height: auto;
                gap: 1rem;
            }
    
            .pollutant-text-ng {
                font-size: 16px;
                line-height: 1.45;
            }
    
            .pollutant-text-ng h4 {
                font-size: 20px;
            }
    
            .pollutant-text-ng h5 {
                font-size: 16px;
            }
    
            .pollutant-image-card-ng {
                height: auto;
                min-height: auto;
                overflow: visible;
            }
    
            .pollutant-image-card-ng img {
                width: 100%;
                height: auto;
                max-height: 60vh;
                max-height: 60dvh;
                object-fit: contain;
                display: block;
            }
    
            .pollutant-caption-ng {
                font-size: 15px;
            }
        }
    </style>
    ''')

    title_label = None
    body_container = None

    def render_modal_content(key: str) -> None:
        nonlocal title_label, body_container

        data = POLLUTANTS[key]
        title_label.set_text(data['title'])
        body_container.clear()

        with body_container:
            with ui.element('div').classes('pollutant-modal-grid-ng'):
                with ui.element('div').classes('pollutant-text-ng'):
                    # sanitize=False porque el HTML es fijo y viene de este archivo.
                    # No usar sanitize=False con texto ingresado por usuarios.
                    ui.html(data['html'], sanitize=False)

                with ui.element('div').classes('pollutant-image-card-ng'):
                    ui.html(
                        f'<img src="{data["image"]}" alt="{data["title"]}">',
                        sanitize=False,
                    )
                    ui.label(data['caption']).classes('pollutant-caption-ng')

    with ui.dialog() as dialog:
        with ui.card().classes('pollutant-dialog-card-ng'):
            with ui.row().classes('pollutant-dialog-header-ng items-center justify-between no-wrap'):
                title_label = ui.label('Título').classes('pollutant-dialog-title-ng')
                ui.button('✕', on_click=dialog.close).props('flat dense').classes('text-black text-xl font-bold')

            body_container = ui.element('div').classes('pollutant-dialog-body-ng')

    def open_pollutant(key: str) -> None:
        render_modal_content(key)
        dialog.open()

    with ui.card().classes('card-pollutants-ng'):
        with ui.row().classes('w-full justify-center'):
            ui.label('Información sobre contaminantes').classes('card-pollutants-title-ng')

        with ui.row().classes('w-full justify-center'):
            ui.label(
                'Para obtener información más detallada sobre los diferentes contaminantes del aire '
                'y cómo proteger su salud, haga clic en una imagen'
            ).classes('card-pollutants-sub-ng')

        with ui.element('div').classes('thumbs-ng'):
            for key, data in POLLUTANTS.items():
                with ui.button(on_click=lambda k=key: open_pollutant(k)).props('flat').classes('thumb-ng'):
                    ui.html(
                        f'<img class="thumb-img-ng" src="{data["thumb"]}" alt="{data["short"]}">',
                        sanitize=False,
                    )
                    ui.label(data['short']).classes('thumb-label-ng')