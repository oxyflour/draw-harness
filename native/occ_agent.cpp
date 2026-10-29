#include <Draw_Interpretor.hxx>
#include <Draw_PluginMacro.hxx>
#include <DBRep.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepBndLib.hxx>
#include <BRepGProp.hxx>
#include <BRepTools.hxx>
#include <BRep_Builder.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRep_Tool.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_ListIteratorOfListOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Iterator.hxx>
#include <GProp_GProps.hxx>
#include <Bnd_Box.hxx>
#include <STEPControl_Writer.hxx>
#include <STEPControl_Reader.hxx>
#include <StlAPI_Writer.hxx>
#include <Standard_Version.hxx>
#include <Standard_Failure.hxx>
#include <tcl.h>
#include <rapidjson/document.h>
#include <rapidjson/stringbuffer.h>
#include <rapidjson/writer.h>
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <streambuf>
#include <string>
#include <vector>

namespace {
using J = rapidjson::Value;
using A = rapidjson::Document::AllocatorType;
J str(const std::string& s, A& a) { return J(s.data(), static_cast<rapidjson::SizeType>(s.size()), a); }
J num(double d) { return std::isfinite(d) ? J(d) : J(); }
std::string encode(const J& v) {
  rapidjson::StringBuffer b;
  rapidjson::Writer<rapidjson::StringBuffer> w(b);
  v.Accept(w);
  return {b.GetString(), b.GetSize()};
}
std::string field(const J& j, const char* key) {
  if (!j.HasMember(key) || !j[key].IsString()) throw std::runtime_error(std::string("Missing string: ") + key);
  std::string s(j[key].GetString(), j[key].GetStringLength());
  if (s.find('\0') != std::string::npos) throw std::runtime_error("NUL is not allowed in arguments");
  return s;
}
bool flag(const J& j, const char* key, bool fallback = false) {
  if (!j.HasMember(key)) return fallback;
  if (!j[key].IsBool()) throw std::runtime_error(std::string("Expected boolean: ") + key);
  return j[key].GetBool();
}
int integer(const J& j, const char* key, int fallback) {
  if (!j.HasMember(key)) return fallback;
  if (!j[key].IsInt()) throw std::runtime_error(std::string("Expected integer: ") + key);
  return j[key].GetInt();
}
const char* types[] = {"compound", "compsolid", "solid", "shell", "face", "wire", "edge", "vertex", "shape"};
TopAbs_ShapeEnum shapeType(const std::string& s) {
  for (int i = 0; i < 8; ++i) if (s == types[i]) return static_cast<TopAbs_ShapeEnum>(i);
  throw std::runtime_error("Type must be compound/compsolid/solid/shell/face/wire/edge/vertex");
}
void nameCheck(const std::string& s) {
  if (s.empty() || s == "." || s.size() > 128) throw std::runtime_error("Invalid shape name");
  for (unsigned char c : s) if (!(std::isalnum(c) || c == '_')) throw std::runtime_error("Use ASCII letters, digits, underscores for shape names");
}
TopoDS_Shape shape(const std::string& name) {
  nameCheck(name);
  auto s = DBRep::GetExisting(TCollection_AsciiString(name.c_str()));
  if (s.IsNull()) throw std::runtime_error("Shape not found: " + name);
  return s;
}
int count(const TopoDS_Shape& s, TopAbs_ShapeEnum type) {
  TopTools_IndexedMapOfShape m;
  TopExp::MapShapes(s, type, m);
  return m.Extent();
}
J point(const gp_Pnt& p, A& a) {
  J v(rapidjson::kArrayType);
  v.PushBack(num(p.X()), a).PushBack(num(p.Y()), a).PushBack(num(p.Z()), a);
  return v;
}
J bounds(const TopoDS_Shape& s, A& a) {
  Bnd_Box b;
  BRepBndLib::AddOptimal(s, b, false, false);
  if (b.IsVoid() || b.IsOpen()) return J();
  double x0, y0, z0, x1, y1, z1;
  b.Get(x0, y0, z0, x1, y1, z1);
  J v(rapidjson::kObjectType);
  v.AddMember("min", point(gp_Pnt(x0, y0, z0), a), a);
  v.AddMember("max", point(gp_Pnt(x1, y1, z1), a), a);
  v.AddMember("size", point(gp_Pnt(x1-x0, y1-y0, z1-z0), a), a);
  return v;
}
J inspect(const std::string& name, A& a) {
  auto s = shape(name);
  J v(rapidjson::kObjectType), counts(rapidjson::kObjectType);
  v.AddMember("name", str(name, a), a);
  v.AddMember("type", str(types[s.ShapeType()], a), a);
  v.AddMember("valid", J(bool(BRepCheck_Analyzer(s).IsValid())), a);
  for (int i = 0; i < 8; ++i) counts.AddMember(str(types[i], a), J(count(s, static_cast<TopAbs_ShapeEnum>(i))), a);
  v.AddMember("topology", counts, a);
  v.AddMember("bbox", bounds(s, a), a);
  GProp_GProps surface, linear, volume;
  BRepGProp::SurfaceProperties(s, surface, false, true);
  BRepGProp::LinearProperties(s, linear, true);
  v.AddMember("area", num(surface.Mass()), a);
  v.AddMember("length", num(linear.Mass()), a);
  if (count(s, TopAbs_SOLID) > 0) {
    BRepGProp::VolumeProperties(s, volume, true, false, true);
    v.AddMember("volume", num(volume.Mass()), a);
    v.AddMember("center_of_mass", point(volume.CentreOfMass(), a), a);
  } else {
    v.AddMember("volume", J(), a);
    v.AddMember("center_of_mass", point(surface.Mass() > 0 ? surface.CentreOfMass() : linear.CentreOfMass(), a), a);
  }
  v.AddMember("units", "model_units (default convention: mm)", a);
  return v;
}
J subshapes(const J& request, A& a) {
  auto s = shape(field(request, "shape"));
  auto type = shapeType(field(request, "type"));
  int offset = integer(request, "offset", 0), limit = integer(request, "limit", 100);
  if (offset < 0 || limit < 1 || limit > 500) throw std::runtime_error("offset >= 0; 1 <= limit <= 500");
  TopTools_IndexedMapOfShape m;
  TopExp::MapShapes(s, type, m);
  J v(rapidjson::kObjectType), items(rapidjson::kArrayType);
  const char* curves[] = {"line", "circle", "ellipse", "hyperbola", "parabola", "bezier", "bspline", "offset", "other"};
  const char* surfaces[] = {"plane", "cylinder", "cone", "sphere", "torus", "bezier", "bspline", "revolution", "extrusion", "offset", "other"};
  for (int i = offset + 1; i <= m.Extent() && i <= offset + limit; ++i) {
    J item(rapidjson::kObjectType);
    item.AddMember("index", i, a);
    item.AddMember("bbox", bounds(m(i), a), a);
    if (type == TopAbs_EDGE) {
      GProp_GProps props;
      BRepGProp::LinearProperties(m(i), props);
      item.AddMember("length", num(props.Mass()), a);
      item.AddMember("center", point(props.CentreOfMass(), a), a);
      if (!BRep_Tool::Degenerated(TopoDS::Edge(m(i)))) {
        BRepAdaptor_Curve c(TopoDS::Edge(m(i)));
        item.AddMember("geometry", str(curves[c.GetType()], a), a);
      }
    } else if (type == TopAbs_FACE) {
      GProp_GProps props;
      BRepGProp::SurfaceProperties(m(i), props);
      item.AddMember("area", num(props.Mass()), a);
      item.AddMember("center", point(props.CentreOfMass(), a), a);
      BRepAdaptor_Surface surf(TopoDS::Face(m(i)));
      item.AddMember("geometry", str(surfaces[surf.GetType()], a), a);
    }
    items.PushBack(item, a);
  }
  v.AddMember("total", m.Extent(), a);
  v.AddMember("offset", offset, a);
  v.AddMember("items", items, a);
  return v;
}

const char* orientation(TopAbs_Orientation value) {
  const char* names[] = {"FORWARD", "REVERSED", "INTERNAL", "EXTERNAL"};
  return names[value];
}
J location(const TopLoc_Location& loc, A& a) {
  const auto& transform = loc.Transformation();
  J rows(rapidjson::kArrayType);
  for (int r = 1; r <= 4; ++r) {
    J row(rapidjson::kArrayType);
    for (int c = 1; c <= 4; ++c) row.PushBack(num(r == 4 ? (c == 4 ? 1.0 : 0.0) : transform.Value(r, c)), a);
    rows.PushBack(row, a);
  }
  return rows;
}
J ancestors(const TopoDS_Shape& root, TopAbs_ShapeEnum childType, TopAbs_ShapeEnum parentType,
            const TopTools_IndexedMapOfShape& nodes, A& a) {
  TopTools_IndexedDataMapOfShapeListOfShape map;
  TopExp::MapShapesAndUniqueAncestors(root, childType, parentType, map);
  J result(rapidjson::kObjectType);
  // Include free edges and isolated vertices with empty ancestor lists.
  for (int id = 1; id <= nodes.Extent(); ++id) {
    if (nodes(id).ShapeType() != childType) continue;
    J parents(rapidjson::kArrayType);
    const int index = map.FindIndex(nodes(id));
    if (index != 0) {
      for (TopTools_ListIteratorOfListOfShape it(map(index)); it.More(); it.Next()) {
        const int parent = nodes.FindIndex(it.Value());
        if (parent == 0) throw std::runtime_error("Topology ancestor missing from graph");
        parents.PushBack(J(parent), a);
      }
    }
    result.AddMember(str(std::to_string(id), a), parents, a);
  }
  return result;
}
J topologyGraph(const J& request, A& a) {
  const auto name = field(request, "shape");
  const auto root = shape(name);
  const bool toFile = request.HasMember("path");
  std::filesystem::path output;
  if (toFile) {
    output = std::filesystem::u8path(field(request, "path"));
    if (!output.is_absolute()) throw std::runtime_error("Use an absolute graph output path");
    if (std::filesystem::exists(output) && !flag(request, "overwrite")) throw std::runtime_error("File exists; set overwrite=true explicitly");
  } else if (flag(request, "overwrite")) {
    throw std::runtime_error("overwrite requires a graph output path");
  }
  TopTools_IndexedMapOfShape nodes, definitions;
  nodes.Add(root.Oriented(TopAbs_FORWARD));
  J uses(rapidjson::kArrayType);
  // A node is (TShape, cumulative Location), independent of orientation.
  // Expand each node once, but keep EVERY direct child use, including duplicates.
  for (int parentId = 1; parentId <= nodes.Extent(); ++parentId) {
    const TopoDS_Shape parent = nodes(parentId); // Copy: inserting children can reallocate the map.
    int ordinal = 0;
    for (TopoDS_Iterator it(parent, false, false); it.More(); it.Next()) {
      const auto& local = it.Value();
      if (local.IsNull()) throw std::runtime_error("Null child in topology graph");
      const auto child = local.Moved(parent.Location(), false).Oriented(TopAbs_FORWARD);
      const int childId = nodes.Add(child);
      if (nodes.Extent() > 100000 || uses.Size() >= 500000) throw std::runtime_error("Topology graph exceeds 100000 nodes or 500000 uses");
      J use(rapidjson::kObjectType);
      use.AddMember("id", J(static_cast<int>(uses.Size()) + 1), a);
      use.AddMember("parent", parentId, a);
      use.AddMember("child", childId, a);
      use.AddMember("ordinal", ++ordinal, a);
      use.AddMember("orientation", str(orientation(local.Orientation()), a), a);
      use.AddMember("location", location(local.Location(), a), a);
      uses.PushBack(use, a);
    }
  }
  // These are the SAME per-type indices used by subshapes/select, not graph IDs.
  TopTools_IndexedMapOfShape typed[8];
  for (int type = 0; type < 8; ++type) TopExp::MapShapes(root, static_cast<TopAbs_ShapeEnum>(type), typed[type]);
  J graph(rapidjson::kObjectType), items(rapidjson::kArrayType);
  for (int id = 1; id <= nodes.Extent(); ++id) {
    const auto& node = nodes(id);
    J item(rapidjson::kObjectType);
    item.AddMember("id", id, a);
    item.AddMember("type", str(types[node.ShapeType()], a), a);
    const int typeIndex = typed[node.ShapeType()].FindIndex(node);
    item.AddMember("type_index", typeIndex == 0 ? J() : J(typeIndex), a);
    item.AddMember("definition_id", definitions.Add(node.Located(TopLoc_Location())), a);
    item.AddMember("location", location(node.Location(), a), a);
    items.PushBack(item, a);
  }
  graph.AddMember("schema_version", 1, a);
  graph.AddMember("shape", str(name, a), a);
  graph.AddMember("root", 1, a);
  graph.AddMember("root_orientation", str(orientation(root.Orientation()), a), a);
  graph.AddMember("node_count", nodes.Extent(), a);
  const auto useCount = uses.Size();
  graph.AddMember("use_count", J(useCount), a);
  graph.AddMember("definition_count", definitions.Extent(), a);
  graph.AddMember("id_scope", "current shape snapshot only", a);
  graph.AddMember("nodes", items, a);
  graph.AddMember("uses", uses, a);
  graph.AddMember("edge_faces", ancestors(root, TopAbs_EDGE, TopAbs_FACE, nodes, a), a);
  graph.AddMember("vertex_edges", ancestors(root, TopAbs_VERTEX, TopAbs_EDGE, nodes, a), a);
  const auto serialized = encode(graph);
  if (!toFile) {
    // Leave room for the RPC envelope under the Python client's 4 MiB bound.
    if (serialized.size() > 3 * 1024 * 1024) throw std::runtime_error("Topology graph exceeds 3 MiB inline limit; supply path to write the complete JSON graph");
    return graph;
  }
  std::ofstream stream(output, std::ios::binary | std::ios::trunc);
  stream.write(serialized.data(), static_cast<std::streamsize>(serialized.size()));
  stream.close();
  if (!stream) throw std::runtime_error("Could not write topology graph file");
  J summary(rapidjson::kObjectType);
  summary.AddMember("schema_version", 1, a);
  summary.AddMember("shape", str(name, a), a);
  summary.AddMember("path", str(output.u8string(), a), a);
  summary.AddMember("format", "json", a);
  summary.AddMember("bytes", J(static_cast<uint64_t>(serialized.size())), a);
  summary.AddMember("node_count", nodes.Extent(), a);
  summary.AddMember("use_count", J(useCount), a);
  return summary;
}

// Bounded streams prevent a noisy DRAW command from flooding tool output.
class Capture : public std::streambuf {
 public:
  std::string text;
  size_t dropped = 0;
 protected:
  std::streamsize xsputn(const char* p, std::streamsize n) override {
    auto take = std::min<size_t>(static_cast<size_t>(n), 65536 - text.size());
    text.append(p, take); dropped += static_cast<size_t>(n) - take;
    return n;
  }
  int overflow(int c) override {
    if (c != traits_type::eof()) { char ch = static_cast<char>(c); xsputn(&ch, 1); }
    return traits_type::not_eof(c);
  }
};
struct Redirect {
  Capture capture;
  std::streambuf *out = std::cout.rdbuf(&capture), *err = std::cerr.rdbuf(&capture);
  ~Redirect() { std::cout.rdbuf(out); std::cerr.rdbuf(err); }
};
J evaluate(Draw_Interpretor& di, const std::string& script, A& a) {
  auto* interp = reinterpret_cast<Tcl_Interp*>(di.Interp());
  Tcl_SetVar(interp, "::occ_harness::output", "", TCL_GLOBAL_ONLY);
  Tcl_SetVar(interp, "::occ_harness::capturing", "1", TCL_GLOBAL_ONLY);
  Redirect redirect;
  int code = Tcl_EvalEx(interp, script.data(), static_cast<int>(script.size()), TCL_EVAL_GLOBAL);
  const std::string result = Tcl_GetStringResult(interp);
  const char* info = code != TCL_OK ? Tcl_GetVar(interp, "errorInfo", TCL_GLOBAL_ONLY) : nullptr;
  std::string errorInfo = info ? info : "";
  const int line = code != TCL_OK ? Tcl_GetErrorLine(interp) : 0;
  const char* output = Tcl_GetVar(interp, "::occ_harness::output", TCL_GLOBAL_ONLY);
  const std::string stdoutText = output ? output : "";
  Tcl_SetVar(interp, "::occ_harness::capturing", "0", TCL_GLOBAL_ONLY);
  J v(rapidjson::kObjectType);
  v.AddMember("ok", J(code == TCL_OK), a);
  v.AddMember("code", code, a);
  v.AddMember("result", str(result.substr(0, 65536), a), a);
  v.AddMember("result_truncated", J(result.size() > 65536), a);
  v.AddMember("stdout", str(stdoutText, a), a);
  v.AddMember("native_output", str(redirect.capture.text, a), a);
  v.AddMember("native_output_truncated", J(redirect.capture.dropped > 0), a);
  if (code != TCL_OK) {
    v.AddMember("error", str(result.substr(0, 65536), a), a);
    v.AddMember("error_info", str(errorInfo.substr(0, 65536), a), a);
    v.AddMember("error_line", line, a);
    v.AddMember("state_may_have_changed", true, a);
  }
  return v;
}

J dispatch(Draw_Interpretor& di, const J& request, A& a) {
  std::string op = field(request, "op");
  if (op == "eval") return evaluate(di, field(request, "script"), a);
  if (op == "inspect") return inspect(field(request, "shape"), a);
  if (op == "subshapes") return subshapes(request, a);
  if (op == "topology_graph") return topologyGraph(request, a);
  if (op == "select") {
    const auto name = field(request, "name"); nameCheck(name);
    auto s = shape(field(request, "shape"));
    TopTools_IndexedMapOfShape m;
    TopExp::MapShapes(s, shapeType(field(request, "type")), m);
    int index = integer(request, "index", 0);
    if (index < 1 || index > m.Extent()) throw std::runtime_error("Subshape index out of range (1-based)");
    DBRep::Set(name.c_str(), m(index));
    return inspect(name, a);
  }
  if (op == "export" || op == "import") {
    auto path = field(request, "path"), name = field(request, "shape"), format = field(request, "format");
    nameCheck(name);
    auto fsPath = std::filesystem::u8path(path);
    if (!fsPath.is_absolute()) throw std::runtime_error("Use an absolute file path");
    if (op == "export") {
      auto s = shape(name);
      if (std::filesystem::exists(fsPath) && !flag(request, "overwrite")) throw std::runtime_error("File exists; set overwrite=true explicitly");
      bool ok = false;
      if (format == "brep") ok = BRepTools::Write(s, path.c_str());
      else if (format == "step") {
        STEPControl_Writer w;
        ok = w.Transfer(s, STEPControl_AsIs) == IFSelect_RetDone && w.Write(path.c_str()) == IFSelect_RetDone;
      } else if (format == "stl") {
        double deflection = 0.1;
        if (request.HasMember("deflection")) {
          if (!request["deflection"].IsNumber()) throw std::runtime_error("deflection must be numeric");
          deflection = request["deflection"].GetDouble();
        }
        if (!(deflection > 0) || !std::isfinite(deflection)) throw std::runtime_error("deflection must be finite and positive");
        BRepMesh_IncrementalMesh mesh(s, deflection, false, 0.5, true);
        if (!mesh.IsDone()) throw std::runtime_error("Meshing failed");
        StlAPI_Writer w; w.ASCIIMode() = false;
        ok = w.Write(s, path.c_str());
      } else throw std::runtime_error("Export format must be brep, step, or stl");
      if (!ok || !std::filesystem::exists(fsPath) || std::filesystem::file_size(fsPath) == 0) throw std::runtime_error("Export failed");
      J v(rapidjson::kObjectType);
      v.AddMember("path", str(path, a), a);
      v.AddMember("format", str(format, a), a);
      v.AddMember("bytes", J(static_cast<uint64_t>(std::filesystem::file_size(fsPath))), a);
      return v;
    }
    if (!std::filesystem::is_regular_file(fsPath)) throw std::runtime_error("Input file does not exist");
    TopoDS_Shape s;
    if (format == "brep") {
      BRep_Builder b;
      if (!BRepTools::Read(s, path.c_str(), b)) throw std::runtime_error("BREP read failed");
    } else if (format == "step") {
      STEPControl_Reader r;
      if (r.ReadFile(path.c_str()) != IFSelect_RetDone || r.TransferRoots() < 1) throw std::runtime_error("STEP read failed");
      s = r.OneShape();
    } else throw std::runtime_error("Import format must be brep or step");
    if (s.IsNull()) throw std::runtime_error("Imported shape is null");
    DBRep::Set(name.c_str(), s);
    return inspect(name, a);
  }
  if (op == "ping") {
    J v(rapidjson::kObjectType);
    v.AddMember("module", "occ-agent-harness", a);
    v.AddMember("version", "0.2.0", a);
    v.AddMember("occt", OCC_VERSION_COMPLETE, a);
    v.AddMember("protocol", 1, a);
    return v;
  }
  if (op == "shutdown") {
    Tcl_SetVar(reinterpret_cast<Tcl_Interp*>(di.Interp()), "::occ_harness::shutdown", "1", TCL_GLOBAL_ONLY);
    J v(rapidjson::kObjectType); v.AddMember("stopped", true, a); return v;
  }
  throw std::runtime_error("Unknown operation: " + op);
}
int rpc(Draw_Interpretor& di, int argc, const char** argv) {
  rapidjson::Document response(rapidjson::kObjectType);
  auto& a = response.GetAllocator();
  try {
    if (argc != 3) throw std::runtime_error("ah_rpc json token");
    rapidjson::Document request;
    request.Parse(argv[1]);
    if (request.HasParseError() || !request.IsObject()) throw std::runtime_error("Invalid JSON request");
    if (field(request, "token") != argv[2]) throw std::runtime_error("Authentication failed");
    // Native library diagnostics are captured even for data exchange operations.
    Redirect redirect;
    J data = dispatch(di, request, a);
    bool ok = !(data.HasMember("ok") && data["ok"].IsBool() && !data["ok"].GetBool());
    response.AddMember("ok", J(ok), a);
    response.AddMember("data", data, a);
    if (!redirect.capture.text.empty()) response.AddMember("diagnostics", str(redirect.capture.text, a), a);
  } catch (const Standard_Failure& e) {
    response.AddMember("ok", false, a);
    response.AddMember("error", str(e.GetMessageString() ? e.GetMessageString() : "OCCT failure", a), a);
  } catch (const std::exception& e) {
    response.AddMember("ok", false, a);
    response.AddMember("error", str(e.what(), a), a);
  }
  di.Reset();
  di << encode(response).c_str();
  return 0; // Transport success; operation status is inside JSON.
}
int inspectCommand(Draw_Interpretor& di, int argc, const char** argv) {
  try {
    if (argc != 2) throw std::runtime_error("ah_inspect shape");
    rapidjson::Document d;
    di << encode(inspect(argv[1], d.GetAllocator())).c_str();
    return 0;
  } catch (const Standard_Failure& e) { di << e.GetMessageString(); return 1; }
    catch (const std::exception& e) { di << e.what(); return 1; }
}
int graphCommand(Draw_Interpretor& di, int argc, const char** argv) {
  try {
    if (argc < 2 || argc > 3) throw std::runtime_error("ah_topology_graph shape ?absolute-json-path?");
    rapidjson::Document request(rapidjson::kObjectType);
    auto& a = request.GetAllocator();
    request.AddMember("shape", str(argv[1], a), a);
    if (argc == 3) request.AddMember("path", str(argv[2], a), a);
    di << encode(topologyGraph(request, a)).c_str();
    return 0;
  } catch (const Standard_Failure& e) { di << e.GetMessageString(); return 1; }
    catch (const std::exception& e) { di << e.what(); return 1; }
}
}
class OccAgent {
 public:
  static void Factory(Draw_Interpretor& di) {
    di.Add("ah_rpc", "ah_rpc json token: structured agent protocol", __FILE__, rpc, "Agent harness");
    di.Add("ah_inspect", "ah_inspect shape: JSON validity, bounds, topology, mass properties", __FILE__, inspectCommand, "Agent harness");
    di.Add("ah_topology_graph", "ah_topology_graph shape [absolute-json-path]: containment uses and adjacency graph", __FILE__, graphCommand, "Agent harness");
  }
};
DPLUGIN(OccAgent)
