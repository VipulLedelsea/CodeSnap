package mn.mde.levy;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.util.List;

public class LevyDao extends BaseDao {
    private final AuditService audit = new AuditService();

    public List<Levy> findByDistrict(Connection c, String id) throws Exception {
        PreparedStatement ps = c.prepareStatement("SELECT * FROM MDE.LEVY_CERT WHERE DISTRICT_ID = ?");
        ps.setString(1, id);
        return map(ps.executeQuery());
    }

    public void certify(Connection c, String id) throws Exception {
        PreparedStatement ps = c.prepareStatement("UPDATE MDE.LEVY_CERT SET CERTIFIED = 'Y' WHERE DISTRICT_ID = ?");
        ps.executeUpdate();
        audit.log("certify", id);
    }
}
