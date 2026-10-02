object frmAidMain: TfrmAidMain
  Left = 200
  Caption = 'District Aid'
  object edtDistrict: TEdit
    Left = 16
  end
  object btnFind: TButton
    Caption = 'Find'
  end
  object dbAid: TDatabase
    AliasName = 'SCHFIN'
    DatabaseName = 'SCHFIN'
  end
  object qryAid: TQuery
    DatabaseName = 'SCHFIN'
    SQL.Strings = (
      'SELECT * FROM AID_PAYMENT'
      'WHERE DISTRICT_ID = :DIST')
  end
  object tblDistrict: TTable
    TableName = 'DISTRICT'
  end
end
