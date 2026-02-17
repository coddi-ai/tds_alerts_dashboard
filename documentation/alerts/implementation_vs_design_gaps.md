# Implementation vs Design - Remaining Gaps

**Document Purpose**: Tracks unresolved differences between design specifications and actual implementation.

**Last Updated**: February 17, 2026  
**Design Documents**: `dashboard_overview.md`, `data_contracts.md`  
**Implementation Document**: `alerts_dashboard_implementation_notes.md`  
**Related Document**: `side_notes_implementation.md` (Implementation details and enhancements)

---

## Status Summary

**Total Remaining Gaps**: 7 (All Data Schema related)

**Resolved Gaps**: 24
- ✅ UI Structure Differences (12) - Resolved Feb 17, 2026
- ✅ Functionality Differences (6) - Resolved Feb 17, 2026
- ✅ Navigation Differences (3) - Resolved Feb 17, 2026
- ✅ Missing Design Features (3) - Resolved Feb 17, 2026

**Note**: Data processing algorithms and additional implementation features have been documented in `side_notes_implementation.md` and are not considered gaps.

---

## Remaining Gaps: Data Schema Differences

These are actual differences in column names, value formats, and data conventions between the design specifications in `data_contracts.md` and the actual data implementation.

### Gap 1: FusionID Format

**Severity**: 🔴 Critical

**Location**: Data Contracts - Consolidated Alerts Schema

**Design Specification**:
- Format: `FUS-{sequential_number}`
- Example: `FUS-001`, `FUS-045`, `FUS-1023`
- Generation: Auto-increment starting from 001

**Actual Implementation**:
- Format: Not specified/enforced in code
- Treated as generic string identifier
- No auto-increment logic visible in implementation

**Impact**: 
- FusionID may not follow the designed naming convention
- Potential integration issues if external systems expect specific format
- No guarantee of sequential numbering

**Found in**:
- Design: `data_contracts.md` - Field Definitions section
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 3.1

**Resolution Needed**: 
- [ ] Update data generation pipeline to enforce FUS-XXX format
- [ ] OR update design documentation to match actual format

---

### Gap 2: Trigger_type Values and Casing

**Severity**: 🟡 Major

**Location**: Data Contracts - Field Definitions

**Design Specification**:
- Values: `'telemetry'` | `'oil'`
- All lowercase
- Future: May support correlation alerts

**Actual Implementation**:
- Values: `'Telemetria'`, `'Tribologia'`, `'Mixto'`
- Title case (capitalized)
- Mixed/correlation alerts (Mixto) already implemented

**Impact**: 
- Different value set requires case-insensitive comparison
- English vs Spanish terminology mismatch
- "Mixto" type exists but wasn't in original design

**Found in**:
- Design: `data_contracts.md` - Field Definitions
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 3.1, Table

**Resolution Needed**: 
- [ ] Standardize on Spanish capitalized format: 'Telemetria' | 'Tribologia' | 'Mixto'
- [ ] Update `data_contracts.md` to reflect actual values
- [ ] Document 'Mixto' type as standard (not future feature)

---

### Gap 3: Oil Reference Column Name

**Severity**: 🟡 Major

**Location**: Data Contracts - Consolidated Alerts Schema

**Design Specification**:
- Column name: `TribologyID`
- Type: string (nullable)
- Description: Reference to oil sample number

**Actual Implementation**:
- Column name: `OilReportNumber`
- Type: string (nullable)
- Same purpose but different name

**Impact**: 
- Code using design specs will fail to find column
- Integration scripts may reference wrong column name

**Found in**:
- Design: `data_contracts.md` - Table schema
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 3.1, Table

**Resolution Needed**: 
- [ ] Choose standard name: `TribologyID` or `OilReportNumber`
- [ ] Update all documentation and code to use consistent name

---

### Gap 4: System Hierarchy Column Names

**Severity**: 🟢 Minor

**Location**: Data Contracts - Field Definitions

**Design Specification**:
- Column names: `System`, `SubSystem`, `Component`
- Title case with capital S and C

**Actual Implementation**:
- Column names: `sistema`, `subsistema`, `componente`
- All lowercase, Spanish naming

**Impact**: 
- Column case mismatch in queries
- Language inconsistency (English vs Spanish)

**Found in**:
- Design: `data_contracts.md` - Field Definitions
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 3.1, Table

**Resolution Needed**: 
- [ ] Standardize casing and language for system hierarchy columns
- [ ] Update `data_contracts.md` to match actual lowercase Spanish names

---

### Gap 5: Timestamp Column Name

**Severity**: 🟢 Minor

**Location**: Data Contracts - Consolidated Alerts Schema

**Design Specification**:
- Column name: `Timestamp`
- Type: datetime

**Actual Implementation**:
- Column name: `Fecha` (Spanish for "Date")
- Type: datetime
- Same purpose but Spanish naming

**Impact**: 
- Column name mismatch
- Language inconsistency

**Found in**:
- Design: `data_contracts.md` - Field Definitions
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 3.1, Table

**Resolution Needed**: 
- [ ] Update `data_contracts.md` to use `Fecha` as actual column name

---

### Gap 6: Missing Values Handling

**Severity**: 🟢 Minor

**Location**: Data Contracts - Field Validation

**Design Specification**:
- No handling specified for missing system values
- Silent null behavior implied

**Actual Implementation**:
- Missing values filled with `'Desconocido'`
- Explicit fill logic: `df['sistema'] = df['sistema'].fillna('Desconocido')`

**Impact**: 
- Default handling improves user experience
- Design didn't specify this behavior

**Found in**:
- Design: `data_contracts.md` - No mention
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 3.1, load_alerts_data

**Resolution Needed**: 
- [ ] Document default value handling in `data_contracts.md`
- [ ] Specify 'Desconocido' as standard for missing sistema/subsistema values

---

### Gap 7: Derived Columns Logic

**Severity**: 🟡 Major

**Location**: Data Contracts vs Implementation

**Design Specification**:
- `has_telemetry`: True if `TelemetryID` is not null
- `has_tribology`: True if `TribologyID` is not null
- Direct null checks on ID columns

**Actual Implementation**:
- `has_telemetry`: Derived from `Trigger_type in ['Telemetria', 'Mixto']`
- `has_tribology`: Derived from `Trigger_type in ['Tribologia', 'Mixto']`
- Logic based on Trigger_type value, not null checks on ID columns

**Impact**: 
- Different derivation logic may produce different results
- Implementation doesn't validate ID columns exist
- Could have Trigger_type='Telemetria' but null TelemetryID

**Found in**:
- Design: `dashboard_overview.md` - Section 3.2
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 3.1, Table

**Resolution Needed**: 
- [ ] Decide on authoritative logic: trigger-based OR null-check based
- [ ] Add validation to ensure Trigger_type matches presence of ID columns
- [ ] Update documentation with chosen approach

---

## Severity Definitions

- 🔴 **Critical**: Data schema mismatches that could cause integration failures or data corruption
- 🟡 **Major**: Significant naming or logic differences requiring code changes
- 🟢 **Minor**: Documentation updates or minor convention differences

---

## Recommendations

### Immediate Actions (Critical):

1. **Standardize FusionID format** (Gap 1)
   - Either enforce FUS-XXX in data pipeline
   - Or document actual format in design

### High Priority (Major):

2. **Standardize Trigger_type values** (Gap 2)
   - Update `data_contracts.md` to: `'Telemetria'` | `'Tribologia'` | `'Mixto'`
   - Document that 'Mixto' is standard, not future feature

3. **Resolve oil column naming** (Gap 3)
   - Choose one: `TribologyID` or `OilReportNumber`
   - Update all references consistently

4. **Clarify derived column logic** (Gap 7)
   - Document trigger-based approach as standard
   - Add validation that trigger matches ID presence

### Low Priority (Minor):

5. **Update column name documentation** (Gaps 4, 5)
   - Document actual Spanish lowercase names: `sistema`, `subsistema`, `componente`, `Fecha`

6. **Document default value handling** (Gap 6)
   - Specify 'Desconocido' for missing system values

---

## Change Log

### February 17, 2026
- **RESOLUTION**: Updated `dashboard_overview.md` to match implementation
  - Resolved 12 UI Structure differences
  - Resolved 6 Functionality differences
  - Resolved 3 Navigation differences
- **DOCUMENTATION**: Created `side_notes_implementation.md`
  - Moved data processing algorithms documentation
  - Moved additional implementation features documentation
- **CLEANUP**: Removed resolved gaps from this document
  - Removed sections 2, 3, 4, 5, 6, 7
  - Kept only Section 1: Data Schema Differences
- **FOCUS**: Document now contains only 7 unresolved data schema gaps

---

**Next Review Date**: When data contracts are updated or implementation changes

**End of Gap Analysis**
