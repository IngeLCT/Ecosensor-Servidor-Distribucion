from nicegui import ui


def add_styles() -> None:
    ui.add_head_html(
        '''
        <style>
        body { 
            margin: 0;
            padding: 0;
            width: 100%;
            height: 100%;
            background: #cce5dc; 
            color: #101820; 
            }
        .connect-shell {
            width: 100%;
            min-height: 100dvh;
            box-sizing: border-box;
        
            display: flex;
            align-items: center;
            justify-content: center;
        
            padding: 20px;
            overflow: hidden;
        }
        .connect-card {
            width: min(560px, 100%);
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 15px;
            text-align: center;
        }
        .connect-title {
            color: #045709;
            font-size: 34px;
            font-weight: 700;
            line-height: 1.1;
        }
        .brand-header {
            display: flex;
            align-items: flex-end;
            justify-content: center;
            gap: 14px;
            flex-wrap: nowrap;
            margin-bottom: 12px;
        }
        .brand-name {
            color: #4a4d2f;
            font-size: 42px;
            font-weight: 700;
            line-height: 1;
            letter-spacing: normal;
            text-shadow: none;
            white-space: nowrap;
        }
        .connect-logo {
            width: 110px !important;
            height: 110px !important;
            max-width: 110px;
            max-height: 110px;
            overflow: visible;
        }
        
        .connect-logo img,
        .connect-logo .q-img__image {
            object-fit: contain !important;
            background-size: contain !important;
            background-repeat: no-repeat !important;
            background-position: center !important;
        }
        .connect-subtitle {
            color: #000;
            font-size: 26px;
            font-weight: 700;
            text-decoration: underline;
            line-height: 1.1;
        }
        .connect-box {
            width: min(460px, 100%);
            display: flex;
            flex-direction: column;
            gap: 12px;
            align-items: stretch;
        }
        .connect-label {
            font-size: 17px;
            font-weight: 700;
            color: #101820;
            text-align: left;
        }
        .connect-input .q-field__control { background: #fff; }
        .action-button {
            min-height: 42px;
            border-radius: 7px !important;
            font-weight: 800 !important;
            letter-spacing: .01em;
            box-shadow: 0 2px 5px rgba(0, 0, 0, .16) !important;
        }
        .connect-button { background: #214e78 !important; color: #fff !important; }
        .secondary-button { background: #eef6fb !important; color: #173b57 !important; border: 1px solid #6f9fbd !important; }
        .secondary-button:hover { background: #dceefa !important; }
        .q-btn.danger-outline-button,
        .q-btn.danger-button,
        .danger-outline-button.bg-primary,
        .danger-button.bg-primary,
        .danger-outline-button.bg-negative,
        .danger-button.bg-negative {
            background: #b00020 !important;
            background-color: #b00020 !important;
            color: #fff !important;
            border: 1px solid #7f0018 !important;
        }
        .q-btn.danger-outline-button .q-btn__content,
        .q-btn.danger-button .q-btn__content {
            color: #fff !important;
        }
        .q-btn.danger-outline-button:hover,
        .q-btn.danger-button:hover {
            background: #8f001a !important;
            background-color: #8f001a !important;
        }
        .dashboard-link {
            color: #132f4c !important;
            font-weight: 900 !important;
            font-size: 20px;
            text-decoration: underline;
        }
        .dashboard {
            width: min(1180px, 100%);
            margin: 0 auto;
            padding: 28px 18px 44px;
            text-align: center;
            font-family: "Arial Narrow", Arial, sans-serif;
        }
        .top-nav {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 10px 18px;
            margin-bottom: 18px;
            font-size: 20px;
            font-weight: 700;
        }
        .brand-title { color: rgb(4, 87, 9); font-size: 28px; font-weight: 700; }
        .section-title {
            color: rgb(4, 4, 52);
            font-size: 26px;
            font-weight: 700;
            text-decoration: underline;
        }
        .dashboard-main-title {
            margin-bottom: 12px;
        }
        .device-select .q-field__control {
            min-height: 48px;
            background: rgba(255, 255, 255, .72);
            border-radius: 8px;
        }
        .device-select .q-field__native,
        .device-select .q-field__input {
            color: rgb(4, 4, 52) !important;
            font-size: 24px;
            font-weight: 700;
            font-family: "Arial Narrow", Arial, sans-serif;
        }
        .device-select .q-field__native > span {
            color: rgb(4, 4, 52) !important;
            font-size: 24px;
            font-weight: 700;
            text-decoration: underline;
        }
        .device-select .q-select__dropdown-icon {
            color: rgb(4, 4, 52) !important;
            font-size: 28px;
        }
        .pollutant-card {
            background: rgba(255, 255, 255, .52);
            border: 1px solid rgba(0, 0, 0, .12);
            border-radius: 8px;
            padding: 16px;
        }
        .thumbs {
            display: grid;
            grid-template-columns: repeat(4, minmax(110px, 1fr));
            gap: 12px;
        }
        .thumb {
            background: #fff;
            border: 1px solid rgba(0, 0, 0, .14);
            border-radius: 8px;
            padding: 8px;
            font-weight: 700;
        }
        .thumb img {
            width: 100%;
            height: 84px;
            object-fit: contain;
        }
        .measure-table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            margin-top: 20px;
        }
        .measure-table th,
        .measure-table td {
            font-size: 24px;
            text-align: center;
            border: 1px solid black;
            padding: 10px;
        }
        .measure-table th { background: #80ffd4; }
        .status-line {
            min-height: 28px;
            font-size: 19px;
            color: #1d332a;
        }
        @media (max-width: 760px) {
            .connect-title { font-size: 30px; }
            .brand-header { gap: 10px; }
            .brand-name { font-size: 34px; }
            .connect-logo { width: 88px !important; height: 88px !important; }
            .connect-subtitle { font-size: 23px; }
            .thumbs { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
            .measure-table th,
            .measure-table td { font-size: 18px; }
        }
        /* --- Nuevos Estilos para Botones --- */
        .q-btn.button1 {
            min-height: 48px !important;
            padding: 12px 25px !important; /* Aumenta el relleno interno para hacer los botones más grandes */
            font-size: 19px !important; /* Hace el texto dentro del botón más grande */
            border-radius: 8px !important; /* Le da esquinas más redondeadas */
            cursor: pointer; /* Indica que es clickeable */
            background: #006fe6 !important; /* Color azul, puedes cambiarlo */
            background-color: #006fe6 !important;
            color: white !important; /* Color del texto del botón */
            border: none !important; /* Elimina el borde predeterminado */
            transition: background-color 0.3s ease; /* Transición suave para el efecto hover */
            margin: 10px; /* Margen alrededor del botón para separarlo de otros elementos */
            display: inline-flex; /* Mantiene el layout correcto del botón Quasar */
            box-shadow: 0 2px 5px rgba(0, 0, 0, .16) !important;
        }

        .q-btn.button1 .q-btn__content {
            color: white !important;
            font-size: 19px !important;
            font-weight: 800 !important;
        }
        
        .q-btn.button1:hover {
            background: #004a99 !important; /* Un tono más oscuro al pasar el ratón */
            background-color: #004a99 !important;
        }
        </style>
        '''
    )
