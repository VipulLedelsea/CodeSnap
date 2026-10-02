unit AidMain;

interface

uses
  Windows, SysUtils, Forms, DBTables, DB;

type
  TfrmAidMain = class(TForm)
    qryAid: TQuery;
    tblDistrict: TTable;
    procedure btnFindClick(Sender: TObject);
  end;

implementation

{$R *.dfm}

procedure TfrmAidMain.btnFindClick(Sender: TObject);
begin
  qryAid.SQL.Clear;
  qryAid.SQL.Add('SELECT * FROM AID_PAYMENT WHERE DISTRICT_ID = ' + edtDistrict.Text);
  qryAid.Open;
  if qryAid.RecordCount = 0 then
    frmNotFound.ShowModal;
end;

end.
